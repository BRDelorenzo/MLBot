import os
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
    Product,
    ProductAttribute,
    ProductCompatibility,
    ProductPricing,
)
from app.models import _utcnow as utcnow
from app.schemas import PricingOut, PricingRequest, ProductOut, ProductUpdateIn

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
):
    query = (
        db.query(Product)
        .options(joinedload(Product.compatibilities), joinedload(Product.attributes))
        .join(ImportItem, Product.import_item_id == ImportItem.id)
    )
    if status:
        query = query.filter(ImportItem.status == status)
    return query.order_by(Product.id.desc()).all()


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = (
        db.query(Product)
        .options(joinedload(Product.compatibilities), joinedload(Product.attributes))
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return product


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdateIn, db: Session = Depends(get_db)):
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
def mock_enrich_product(product_id: int, db: Session = Depends(get_db)):
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


@router.post("/{product_id}/pricing/calculate", response_model=PricingOut)
def calculate_pricing(product_id: int, payload: PricingRequest, db: Session = Depends(get_db)):
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

    db.commit()
    db.refresh(pricing)
    return pricing


@router.post("/{product_id}/images/upload")
async def upload_product_images(
    product_id: int,
    files: list[UploadFile] = File(..., description="Imagens do produto"),
    db: Session = Depends(get_db),
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
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Imagem {file.filename} excede o limite de {settings.max_image_size_mb}MB",
            )

        ext = os.path.splitext(file.filename or "img.jpg")[1] or ".jpg"
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
