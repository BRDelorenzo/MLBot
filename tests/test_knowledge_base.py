import os
import tempfile
from io import BytesIO
from unittest.mock import patch

import fitz  # PyMuPDF


def _create_test_pdf(content_lines: list[str]) -> bytes:
    """Cria um PDF de teste com o conteúdo fornecido."""
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in content_lines:
        page.insert_text((72, y), line, fontsize=10)
        y += 16
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_kb_upload_pdf(client):
    pdf_data = _create_test_pdf([
        "FRONT BRAKE",
        "53170-MEL-006  COMP., R. FR. BRAKE DISK",
        "For CG 160 Titan 2018-2024",
    ])
    resp = client.post(
        "/kb/upload",
        files={"file": ("catalogo.pdf", BytesIO(pdf_data), "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "catalogo.pdf"
    assert data["brand"] == "Honda"


def test_kb_upload_rejects_non_pdf(client):
    resp = client.post(
        "/kb/upload",
        files={"file": ("catalogo.txt", BytesIO(b"data"), "text/plain")},
    )
    assert resp.status_code == 400


def test_kb_list_documents_empty(client):
    resp = client.get("/kb/documents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_kb_stats_empty(client):
    resp = client.get("/kb/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_documents"] == 0
    assert data["total_entries"] == 0


def test_kb_search_not_found(client):
    resp = client.get("/kb/search?oem=NOTEXIST")
    assert resp.status_code == 200
    data = resp.json()
    assert data["found_in_kb"] is False
    assert data["entries"] == []


def test_kb_search_found(client, db, user_id):
    """Insere entry diretamente e busca."""
    from app.models import KBDocument, KBDocumentStatus, KBEntry

    doc = KBDocument(
        user_id=user_id,
        filename="test.pdf",
        storage_path="/tmp/test.pdf",
        status=KBDocumentStatus.processed,
    )
    db.add(doc)
    db.flush()

    entry = KBEntry(
        document_id=doc.id,
        oem_code="53170-MEL-006",
        oem_code_normalized="53170-MEL-006",
        honda_part_name="COMP., R. FR. BRAKE DISK",
        section_context="FRONT BRAKE",
        page_number=1,
    )
    db.add(entry)
    db.commit()

    resp = client.get("/kb/search?oem=53170-MEL-006")
    data = resp.json()
    assert data["found_in_kb"] is True
    assert len(data["entries"]) == 1
    assert data["entries"][0]["honda_part_name"] == "COMP., R. FR. BRAKE DISK"


def test_kb_delete_document(client, db, user_id, tmp_path):
    from app.config import settings
    from app.models import KBDocument, KBDocumentStatus

    # Cria arquivo dentro de kb_upload_dir — delete valida o prefixo por segurança.
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    settings.kb_upload_dir = str(kb_dir)
    tmp = kb_dir / "to_delete.pdf"
    tmp.write_bytes(b"fake pdf")

    doc = KBDocument(
        user_id=user_id,
        filename="to_delete.pdf",
        storage_path=str(tmp),
        status=KBDocumentStatus.processed,
    )
    db.add(doc)
    db.commit()

    resp = client.delete(f"/kb/documents/{doc.id}")
    assert resp.status_code == 200
    assert not tmp.exists()


def test_kb_delete_not_found(client):
    resp = client.delete("/kb/documents/999")
    assert resp.status_code == 404


def test_kb_entries_list(client, db, user_id):
    from app.models import KBDocument, KBDocumentStatus, KBEntry

    doc = KBDocument(
        user_id=user_id,
        filename="entries_test.pdf",
        storage_path="/tmp/test.pdf",
        status=KBDocumentStatus.processed,
    )
    db.add(doc)
    db.flush()

    for i in range(3):
        db.add(KBEntry(
            document_id=doc.id,
            oem_code=f"OEM-{i:03d}",
            oem_code_normalized=f"OEM-{i:03d}",
            page_number=i + 1,
        ))
    db.commit()

    resp = client.get(f"/kb/entries?document_id={doc.id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_kb_get_document(client, db, user_id):
    from app.models import KBDocument, KBDocumentStatus

    doc = KBDocument(
        user_id=user_id,
        filename="detail.pdf",
        storage_path="/tmp/test.pdf",
        status=KBDocumentStatus.processed,
        page_count=10,
    )
    db.add(doc)
    db.commit()

    resp = client.get(f"/kb/documents/{doc.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "detail.pdf"
    assert data["page_count"] == 10


def test_kb_get_document_not_found(client):
    resp = client.get("/kb/documents/999")
    assert resp.status_code == 404
