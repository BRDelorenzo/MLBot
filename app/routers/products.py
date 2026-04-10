import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.models import (
    Image,
    ImageType,
    ImportItem,
    ItemStatus,
    Listing,
    Product,
    ProductAttribute,
    ProductCompatibility,
    ProductPricing,
    User,
)
from app.models import _utcnow as utcnow
from app.schemas import EnrichmentResult, PricingOut, PricingRequest, ProductOut, ProductUpdateIn
from app.services.ai_enrichment import enrich_product as ai_enrich, lookup_kb, _get_honda_price
from app.services.auth import get_current_user, get_optional_user
from app.services.image_processing import remove_background

router = APIRouter(prefix="/products", tags=["products"])

MAX_IMAGE_BYTES = settings.max_image_size_mb * 1024 * 1024
MAX_IMAGES_PER_REQUEST = 10


def _ensure_upload_dir(product_oem: str) -> Path:
    path = Path(settings.upload_dir) / product_oem
    path.mkdir(parents=True, exist_ok=True)
    return path


def calculate_suggested_price(
    cost: float,
    estimated_shipping: float,
    commission_percent: float,
    fixed_fee: float,
    margin_percent: float,
) -> float:
    denominator = 1 - commission_percent - margin_percent
    if denominator <= 0:
        raise ValueError("Comissão + margem não podem ser maiores ou iguais a 100%.")
    return round((cost + estimated_shipping + fixed_fee) / denominator, 2)


@router.get("", response_model=list[ProductOut])
def list_products(
    status: ItemStatus | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    query = (
        db.query(Product)
        .options(
            joinedload(Product.import_item),
            joinedload(Product.compatibilities),
            joinedload(Product.attributes),
            joinedload(Product.images),
            joinedload(Product.pricing),
            joinedload(Product.listing),
        )
        .join(ImportItem, Product.import_item_id == ImportItem.id)
    )
    if user:
        query = query.filter(Product.user_id == user.id)
    if status:
        query = query.filter(ImportItem.status == status)
    return query.order_by(Product.id.desc()).all()


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = (
        db.query(Product)
        .options(
            joinedload(Product.import_item),
            joinedload(Product.compatibilities),
            joinedload(Product.attributes),
            joinedload(Product.images),
            joinedload(Product.pricing),
            joinedload(Product.listing),
        )
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return product


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/mock-enrich", response_model=ProductOut)
def mock_enrich_product(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    product.part_name = product.part_name or "Pastilha de Freio Dianteira"
    product.brand = product.brand or "Honda"
    product.category = product.category or "Freio"
    product.technical_description = "Peça de reposição para sistema de freio dianteiro."
    product.confidence_level = 80
    product.source_data = "mock_provider"
    product.last_confirmed_at = utcnow()

    if not product.compatibilities:
        product.compatibilities.append(
            ProductCompatibility(
                motorcycle_brand="Honda",
                motorcycle_model="CG 160 Titan",
                year_start=2018,
                year_end=2024,
                notes="Compatibilidade simulada para desenvolvimento",
            )
        )

    if not product.attributes:
        product.attributes.append(ProductAttribute(name="Posição", value="Dianteira"))
        product.attributes.append(ProductAttribute(name="Material", value="Semi-metálico"))

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
    if import_item:
        import_item.status = ItemStatus.awaiting_review

    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/ai-enrich", response_model=EnrichmentResult)
def ai_enrich_product(
    product_id: int,
    provider: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    product = (
        db.query(Product)
        .options(joinedload(Product.compatibilities), joinedload(Product.attributes))
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
    if import_item:
        import_item.status = ItemStatus.enriching
        db.commit()

    try:
        result = ai_enrich(product, db, provider_id=provider)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        if import_item:
            import_item.status = ItemStatus.imported
            db.commit()
        raise HTTPException(status_code=500, detail=f"Erro no enriquecimento IA: {exc}") from exc

    return result


@router.post("/bulk-enrich")
def bulk_ai_enrich(batch_id: int = Query(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Enriquece todos os produtos não-enriquecidos de um batch."""
    items = (
        db.query(ImportItem)
        .filter(ImportItem.batch_id == batch_id)
        .filter(ImportItem.status.in_([ItemStatus.imported, ItemStatus.normalized]))
        .all()
    )

    if not items:
        raise HTTPException(status_code=404, detail="Nenhum item pendente para enriquecer neste lote")

    results = []
    errors = []
    for item in items:
        product = db.query(Product).filter(Product.import_item_id == item.id).first()
        if not product:
            continue
        try:
            result = ai_enrich(product, db)
            results.append(result)
        except Exception as exc:
            errors.append({"oem": product.oem, "error": str(exc)})

    return {
        "enriched": len(results),
        "errors": len(errors),
        "error_details": errors,
        "results": results,
    }


@router.get("/{product_id}/pricing/info")
def get_pricing_info(product_id: int, db: Session = Depends(get_db)):
    """Retorna dados de pricing existentes + preço Honda da KB."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    honda_price = None
    kb_entries = lookup_kb(product.oem, db)
    if kb_entries:
        honda_price = _get_honda_price(kb_entries)

    pricing = product.pricing
    return {
        "honda_price": honda_price,
        "cost": float(pricing.cost) if pricing else honda_price,
        "estimated_shipping": float(pricing.estimated_shipping) if pricing else 0,
        "commission_percent": float(pricing.commission_percent) if pricing else 0.16,
        "fixed_fee": float(pricing.fixed_fee) if pricing else 0,
        "margin_percent": float(pricing.margin_percent) if pricing else 0.20,
        "suggested_price": float(pricing.suggested_price) if pricing and pricing.suggested_price else None,
        "final_price": float(pricing.final_price) if pricing and pricing.final_price else None,
    }


@router.post("/{product_id}/pricing/calculate", response_model=PricingOut)
def calculate_pricing(product_id: int, payload: PricingRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    try:
        suggested_price = calculate_suggested_price(
            cost=payload.cost,
            estimated_shipping=payload.estimated_shipping,
            commission_percent=payload.commission_percent,
            fixed_fee=payload.fixed_fee,
            margin_percent=payload.margin_percent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pricing = product.pricing
    if not pricing:
        pricing = ProductPricing(product_id=product.id, cost=payload.cost)
        db.add(pricing)

    pricing.cost = payload.cost
    pricing.estimated_shipping = payload.estimated_shipping
    pricing.commission_percent = payload.commission_percent
    pricing.fixed_fee = payload.fixed_fee
    pricing.margin_percent = payload.margin_percent
    pricing.suggested_price = suggested_price
    pricing.final_price = suggested_price

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
    if import_item and import_item.status in (
        ItemStatus.enriched,
        ItemStatus.awaiting_review,
    ):
        import_item.status = ItemStatus.awaiting_photos

    db.commit()
    db.refresh(pricing)
    return pricing


@router.post("/{product_id}/images/upload")
async def upload_product_images(
    product_id: int,
    files: list[UploadFile] = File(..., description="Imagens do produto"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    if not files:
        raise HTTPException(status_code=400, detail="Nenhuma imagem enviada")

    if len(files) > MAX_IMAGES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_IMAGES_PER_REQUEST} imagens por vez")

    upload_dir = _ensure_upload_dir(product.oem)
    next_index = len([img for img in product.images if img.image_type == ImageType.original]) + 1
    uploaded = []

    for file in files:
        if not (file.content_type or "").startswith("image/"):
            raise HTTPException(status_code=400, detail=f"Arquivo inválido: {file.filename}")

        content = await file.read()

        # Valida magic bytes da imagem
        _IMAGE_SIGNATURES = {
            b"\xff\xd8\xff": "image/jpeg",
            b"\x89PNG\r\n\x1a\n": "image/png",
            b"RIFF": "image/webp",  # WebP starts with RIFF
            b"GIF87a": "image/gif",
            b"GIF89a": "image/gif",
        }
        if not any(content[:8].startswith(sig) for sig in _IMAGE_SIGNATURES):
            raise HTTPException(status_code=400, detail=f"Arquivo {file.filename} não é uma imagem válida (magic bytes inválidos)")

        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Imagem {file.filename} excede o limite de {settings.max_image_size_mb}MB",
            )

        # Extrai extensão segura (sem path traversal)
        safe_original = Path(file.filename or "img.jpg").name
        ext = os.path.splitext(safe_original)[1] or ".jpg"
        if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            raise HTTPException(status_code=400, detail=f"Extensão não permitida: {ext}")
        filename = f"{product.oem}_original_{next_index}{ext}"
        file_path = upload_dir / filename

        with open(file_path, "wb") as f:
            f.write(content)

        image = Image(
            product_id=product.id,
            image_type=ImageType.original,
            sort_order=next_index,
            filename=filename,
            storage_path=str(file_path),
            mime_type=file.content_type,
            status="uploaded",
        )
        db.add(image)
        uploaded.append(filename)
        next_index += 1

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
    if import_item:
        import_item.status = ItemStatus.photos_received

    db.commit()

    return {
        "message": "Imagens salvas com sucesso",
        "files": uploaded,
    }


@router.post("/{product_id}/images/process-background")
def process_images_background(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Remove o fundo de todas as imagens originais e gera versões com fundo branco."""
    product = (
        db.query(Product)
        .options(joinedload(Product.images))
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    originals = [img for img in product.images if img.image_type == ImageType.original]
    if not originals:
        raise HTTPException(status_code=400, detail="Nenhuma imagem original encontrada. Faça upload primeiro.")

    # Remove imagens processadas anteriores
    old_processed = [img for img in product.images if img.image_type == ImageType.processed]
    for old in old_processed:
        if old.storage_path and Path(old.storage_path).exists():
            Path(old.storage_path).unlink()
        db.delete(old)

    processed = []
    errors = []
    upload_dir = _ensure_upload_dir(product.oem)

    for img in originals:
        output_filename = f"{product.oem}_processed_{img.sort_order}.jpg"
        output_path = str(upload_dir / output_filename)

        try:
            remove_background(img.storage_path, output_path)

            processed_img = Image(
                product_id=product.id,
                image_type=ImageType.processed,
                sort_order=img.sort_order,
                filename=output_filename,
                storage_path=output_path,
                mime_type="image/jpeg",
                status="processed",
            )
            db.add(processed_img)
            processed.append(output_filename)
        except RuntimeError as exc:
            errors.append({"file": img.filename, "error": str(exc)})

    if processed:
        import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
        if import_item and import_item.status in (
            ItemStatus.photos_received,
            ItemStatus.processing_images,
        ):
            import_item.status = ItemStatus.processed

    db.commit()

    return {
        "message": f"{len(processed)} imagem(ns) processada(s) com fundo branco",
        "processed": processed,
        "errors": errors,
    }
