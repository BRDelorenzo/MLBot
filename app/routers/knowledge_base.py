import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import KBDocument, KBDocumentStatus, KBEntry, User, UserRole
from app.services.auth import get_current_user, require_role
from app.routers.batches import normalize_oem
from app.schemas import KBDocumentOut, KBEntryOut, KBSearchResult
from app.services.kb_parser import process_kb_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


def _ensure_kb_dir() -> Path:
    path = Path(settings.kb_upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _process_document_bg(document_id: int):
    """Processa o documento em background usando uma sessão própria."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        process_kb_document(document_id, db)
    finally:
        db.close()


@router.post("/upload", response_model=KBDocumentOut)
async def upload_kb_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    brand: str = Query(default="Honda"),
    document_type: str = Query(default="parts_catalog"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF")

    # Quotas por tenant — evita enchimento de storage e DoS por acumulação.
    active_docs = (
        db.query(KBDocument)
        .filter(KBDocument.user_id == user.id)
        .filter(KBDocument.status != KBDocumentStatus.error)
        .count()
    )
    if active_docs >= settings.kb_max_docs_per_tenant:
        raise HTTPException(
            status_code=400,
            detail=f"Limite de {settings.kb_max_docs_per_tenant} documentos ativos atingido.",
        )

    # Nome seguro para evitar path traversal
    original_name = Path(file.filename).name
    safe_name = f"{secrets.token_hex(8)}_{original_name}"

    upload_dir = _ensure_kb_dir()
    file_path = upload_dir / safe_name

    max_kb_size = settings.kb_max_pdf_size_mb * 1024 * 1024
    chunk_size = 1024 * 1024  # 1MB por chunk
    total_written = 0
    first_chunk = True

    with open(file_path, "wb") as f:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break

            # Valida magic bytes PDF no primeiro chunk
            if first_chunk:
                if not chunk[:5].startswith(b"%PDF-"):
                    f.close()
                    file_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="Arquivo inválido: não é um PDF válido")
                first_chunk = False

            total_written += len(chunk)
            if total_written > max_kb_size:
                f.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=400,
                    detail=f"Arquivo excede o limite de {settings.kb_max_pdf_size_mb}MB",
                )

            f.write(chunk)

    if total_written == 0:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    document = KBDocument(
        user_id=user.id,
        filename=original_name,
        storage_path=str(file_path),
        document_type=document_type,
        brand=brand,
        status=KBDocumentStatus.pending,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    background_tasks.add_task(_process_document_bg, document.id)

    return _document_with_count(document, db)


@router.get("/documents", response_model=list[KBDocumentOut])
def list_kb_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    documents = (
        db.query(KBDocument)
        .filter(KBDocument.user_id == user.id)
        .order_by(KBDocument.id.desc())
        .all()
    )
    return [_document_with_count(doc, db) for doc in documents]


@router.get("/documents/{document_id}", response_model=KBDocumentOut)
def get_kb_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document = (
        db.query(KBDocument)
        .filter(KBDocument.id == document_id, KBDocument.user_id == user.id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return _document_with_count(document, db)


@router.delete("/documents/{document_id}")
def delete_kb_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.admin, UserRole.operator))):
    document = db.query(KBDocument).filter(KBDocument.id == document_id, KBDocument.user_id == user.id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")

    # Remove arquivo físico — defense-in-depth: só deleta dentro de kb_upload_dir
    kb_root = Path(settings.kb_upload_dir).resolve()
    try:
        file_path = Path(document.storage_path).resolve()
        safe = file_path.is_relative_to(kb_root)
    except (OSError, ValueError):
        safe = False

    if not safe:
        logger.error(
            "Tentativa de deletar KB document fora do diretório canônico: id=%s path=%s",
            document.id, document.storage_path,
        )
    elif file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            # Órfão no filesystem é preferível a órfão no DB — loga e segue.
            logger.exception("Falha ao remover arquivo KB id=%s path=%s", document.id, file_path)

    db.delete(document)
    db.commit()
    return {"message": "Documento removido", "id": document_id}


@router.get("/search", response_model=KBSearchResult)
def search_kb(oem: str = Query(..., min_length=3), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    normalized = normalize_oem(oem)
    entries = (
        db.query(KBEntry)
        .join(KBDocument, KBEntry.document_id == KBDocument.id)
        .filter(KBEntry.oem_code_normalized == normalized)
        .filter(KBDocument.user_id == user.id)
        .all()
    )
    return KBSearchResult(
        oem_code=normalized,
        entries=entries,
        found_in_kb=len(entries) > 0,
    )


@router.get("/entries", response_model=list[KBEntryOut])
def list_kb_entries(
    document_id: int = Query(...),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = (
        db.query(KBDocument)
        .filter(KBDocument.id == document_id, KBDocument.user_id == user.id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")

    return (
        db.query(KBEntry)
        .filter(KBEntry.document_id == document_id)
        .order_by(KBEntry.page_number.asc(), KBEntry.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/stats")
def kb_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    total_documents = (
        db.query(KBDocument).filter(KBDocument.user_id == user.id).count()
    )
    total_entries = (
        db.query(KBEntry)
        .join(KBDocument, KBEntry.document_id == KBDocument.id)
        .filter(KBDocument.user_id == user.id)
        .count()
    )
    unique_oems = (
        db.query(KBEntry.oem_code_normalized)
        .join(KBDocument, KBEntry.document_id == KBDocument.id)
        .filter(KBDocument.user_id == user.id)
        .distinct()
        .count()
    )

    from app.models import Product
    total_products = (
        db.query(Product).filter(Product.user_id == user.id).count()
    )
    if total_products > 0:
        user_oems_subq = (
            db.query(KBEntry.oem_code_normalized)
            .join(KBDocument, KBEntry.document_id == KBDocument.id)
            .filter(KBDocument.user_id == user.id)
        )
        matched = (
            db.query(Product)
            .filter(Product.user_id == user.id)
            .filter(Product.oem.in_(user_oems_subq))
            .count()
        )
        coverage_pct = round(matched / total_products * 100, 1)
    else:
        matched = 0
        coverage_pct = 0

    return {
        "total_documents": total_documents,
        "total_entries": total_entries,
        "unique_oems": unique_oems,
        "products_matched": matched,
        "products_total": total_products,
        "coverage_pct": coverage_pct,
    }


@router.get("/ai-providers")
def list_ai_providers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Retorna status de todos os providers de IA do usuário."""
    from app.services.ai_enrichment import get_all_provider_status
    return get_all_provider_status(user.id, db)


@router.post("/ai-providers/{provider_id}")
def configure_ai_provider(
    provider_id: str,
    api_key: str = Body(..., min_length=10, embed=True),
    model: str | None = Body(default=None, embed=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Configura a API key e modelo de um provider do usuário."""
    from app.services.ai_enrichment import PROVIDERS, get_provider_config, set_provider_config

    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider desconhecido: {provider_id}")

    set_provider_config(user.id, provider_id, api_key, model, db)
    cfg = get_provider_config(user.id, provider_id, db)
    k = cfg.api_key
    masked = k[:4] + "..." + k[-4:] if len(k) > 12 else "***"
    return {
        "provider": provider_id,
        "configured": True,
        "masked_key": masked,
        "model": cfg.model,
    }


@router.delete("/ai-providers/{provider_id}")
def remove_ai_provider(provider_id: str, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.admin, UserRole.operator))):
    """Remove a API key de um provider do usuário."""
    from app.services.ai_enrichment import PROVIDERS, remove_provider_config

    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider desconhecido: {provider_id}")

    remove_provider_config(user.id, provider_id, db)
    return {"provider": provider_id, "configured": False}


def _document_with_count(document: KBDocument, db: Session) -> dict:
    """Retorna documento com entry_count calculado."""
    count = db.query(KBEntry).filter(KBEntry.document_id == document.id).count()
    return {
        "id": document.id,
        "filename": document.filename,
        "document_type": document.document_type,
        "brand": document.brand,
        "page_count": document.page_count,
        "status": document.status,
        "error_message": document.error_message,
        "created_at": document.created_at,
        "entry_count": count,
    }
