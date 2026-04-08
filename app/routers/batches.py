from io import StringIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportBatch, ImportItem, ItemStatus, Product, User
from app.schemas import BatchOut, ImportItemOut
from app.services.auth import get_optional_user

router = APIRouter(prefix="/batches", tags=["batches"])


def normalize_oem(value: str) -> str:
    return "".join(ch for ch in value.strip().upper() if ch.isalnum() or ch in ["-", "_"])


def parse_txt_content(raw_text: str) -> list[str]:
    lines = [line.strip() for line in StringIO(raw_text).readlines()]
    cleaned = [line for line in lines if line]

    seen = set()
    unique = []
    for item in cleaned:
        normalized = normalize_oem(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)

    return unique


@router.post("/import", response_model=BatchOut)
async def import_oem_batch(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    if not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .txt")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Arquivo precisa estar em UTF-8") from exc

    oems = parse_txt_content(text)
    if not oems:
        raise HTTPException(status_code=400, detail="Nenhum OEM válido encontrado")

    batch = ImportBatch(
        filename=file.filename,
        user_id=user.id if user else None,
        total_items=len(oems),
        total_valid=len(oems),
        total_invalid=0,
    )
    db.add(batch)
    db.flush()

    for oem in oems:
        item = ImportItem(
            batch_id=batch.id,
            oem_raw=oem,
            oem_normalized=oem,
            status=ItemStatus.imported,
        )
        db.add(item)
        db.flush()

        # Verifica duplicatas apenas do mesmo usuário
        q = db.query(Product).filter(Product.oem == oem)
        if user:
            q = q.filter(Product.user_id == user.id)
        existing_product = q.first()
        if existing_product:
            item.status = ItemStatus.awaiting_review
            continue

        product = Product(
            import_item_id=item.id,
            user_id=user.id if user else None,
            oem=oem,
            source_data="internal_seed",
            confidence_level=0,
        )
        db.add(product)
        item.status = ItemStatus.normalized

    db.commit()
    db.refresh(batch)
    return batch


@router.get("", response_model=list[BatchOut])
def list_batches(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    q = db.query(ImportBatch)
    if user:
        q = q.filter(ImportBatch.user_id == user.id)
    return q.order_by(ImportBatch.id.desc()).all()


@router.get("/{batch_id}/items", response_model=list[ImportItemOut])
def list_batch_items(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(ImportBatch).filter(ImportBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    return db.query(ImportItem).filter(ImportItem.batch_id == batch_id).order_by(ImportItem.id.asc()).all()
