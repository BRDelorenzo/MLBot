"""Parser de catálogos Honda em PDF para extração de OEMs, descrições e preços.

Formato esperado do catálogo Honda (3 colunas por item):
  CÓDIGO DO PRODUTO    (ex: 0123A-K01-305)
  DESCRIÇÃO DO PRODUTO (ex: KIT REVISAO HOP SH15)
  VALOR                (ex: 65,41)
"""

import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import fitz  # PyMuPDF
from sqlalchemy.orm import Session

from app.models import KBDocument, KBDocumentStatus, KBEntry
from app.routers.batches import normalize_oem

logger = logging.getLogger(__name__)

# Padrão Honda OEM: dígitos + letra opcional, hífen, alfanum, hífen, alfanum, sufixo opcional
# Exemplos: 0123A-K01-305, 53170-MEL-006, 06170-K1S-B00ZA, 01500-KSS-305 G
OEM_PATTERN = re.compile(
    r"^(\d{2,5}[A-Z]?-[A-Z0-9]{2,4}-[A-Z0-9]{2,6}(?:\s+[A-Z])?)$",
    re.IGNORECASE,
)

# Padrão para valor monetário brasileiro: 1.234,56 ou 65,41
PRICE_PATTERN = re.compile(r"^[\d.,]+$")

# Header do catálogo (para ignorar)
HEADER_TEXTS = {"CÓDIGO DO PRODUTO", "DESCRIÇÃO DO PRODUTO", "VALOR", "CODIGO DO PRODUTO", "DESCRICAO DO PRODUTO"}


def _parse_price(text: str) -> Decimal | None:
    """Converte string de preço brasileiro para Decimal."""
    try:
        # Remove pontos de milhar, troca vírgula por ponto
        cleaned = text.strip().replace(".", "").replace(",", ".")
        value = Decimal(cleaned)
        return value if value > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _is_header(line: str) -> bool:
    """Verifica se a linha é um cabeçalho do catálogo."""
    normalized = line.strip().upper()
    # Remove acentos problemáticos de encoding
    normalized = normalized.replace("Ã", "A").replace("Ç", "C").replace("Ó", "O")
    return normalized in HEADER_TEXTS or "CODIGO" in normalized or "DESCRI" in normalized


def parse_pdf(file_path: str) -> tuple[list[dict], int]:
    """Extrai OEMs, descrições e preços de um catálogo Honda PDF.

    O catálogo segue o padrão de 3 linhas por item:
      Linha 1: Código OEM
      Linha 2: Descrição da peça
      Linha 3: Valor (preço)

    Retorna (entries, page_count).
    """
    doc = fitz.open(file_path)
    entries = []
    seen_oems: set[str] = set()

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Filtra headers
        lines = [line for line in lines if not _is_header(line)]

        # Processa em blocos de 3: código, descrição, valor
        i = 0
        while i < len(lines):
            line = lines[i]
            oem_match = OEM_PATTERN.match(line)

            if oem_match:
                raw_oem = oem_match.group(1).strip()
                normalized = normalize_oem(raw_oem)

                if not normalized or len(normalized) < 6:
                    i += 1
                    continue

                # Dedup
                if normalized in seen_oems:
                    i += 3  # Pula o bloco inteiro
                    continue
                seen_oems.add(normalized)

                # Linha seguinte = descrição
                description = lines[i + 1] if i + 1 < len(lines) else None
                # Evita que um OEM ou preço seja lido como descrição
                if description and (OEM_PATTERN.match(description) or PRICE_PATTERN.match(description)):
                    description = None

                # Linha após descrição = valor
                price = None
                price_line_idx = i + 2 if description else i + 1
                if price_line_idx < len(lines):
                    price = _parse_price(lines[price_line_idx])

                # Contexto: bloco de 3 linhas
                block_end = min(i + 3, len(lines))
                raw_text_block = "\n".join(lines[i:block_end])

                entries.append({
                    "oem_code": raw_oem,
                    "oem_code_normalized": normalized,
                    "honda_part_name": description,
                    "honda_price": price,
                    "page_number": page_num + 1,
                    "raw_text_block": raw_text_block,
                })

                i += 3  # Avança o bloco completo
            else:
                i += 1

    total_pages = len(doc)
    doc.close()
    logger.info(
        "PDF %s: extraídos %d OEMs de %d páginas",
        file_path, len(entries), total_pages,
    )
    return entries, total_pages


def process_kb_document(document_id: int, db: Session):
    """Processa um KBDocument: faz parse do PDF e cria KBEntry rows."""
    document = db.query(KBDocument).filter(KBDocument.id == document_id).first()
    if not document:
        return

    document.status = KBDocumentStatus.processing
    db.commit()

    try:
        file_path = document.storage_path
        if not Path(file_path).exists():
            raise FileNotFoundError(f"PDF não encontrado: {file_path}")

        entries, page_count = parse_pdf(file_path)
        document.page_count = page_count

        for entry_data in entries:
            kb_entry = KBEntry(
                document_id=document.id,
                oem_code=entry_data["oem_code"],
                oem_code_normalized=entry_data["oem_code_normalized"],
                honda_part_name=entry_data["honda_part_name"],
                honda_price=entry_data["honda_price"],
                page_number=entry_data["page_number"],
                raw_text_block=entry_data["raw_text_block"],
            )
            db.add(kb_entry)

        document.status = KBDocumentStatus.processed
        db.commit()
        logger.info("Documento %d processado: %d entradas criadas", document_id, len(entries))

    except Exception as exc:
        db.rollback()
        document.status = KBDocumentStatus.error
        document.error_message = str(exc)[:500]
        db.commit()
        logger.exception("Erro ao processar documento %d", document_id)
