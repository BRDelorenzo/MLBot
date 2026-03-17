from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

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
from app.schemas import PricingOut, PricingRequest, ProductOut, ProductUpdateIn

router = APIRouter(prefix="/products", tags=["products"])


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
    status: Optional[ItemStatus] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Product).join(ImportItem, Product.import_item_id == ImportItem.id)
    if status:
        query = query.filter(ImportItem.status == status)
    return query.order_by(Product.id.desc()).all()


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
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
    product.last_confirmed_at = datetime.utcnow()

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
        raise HTTPException(status_code=400, detail=str(exc))

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
    files: Annotated[list[UploadFile], File(...)],
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    if not files:
        raise HTTPException(status_code=400, detail="Nenhuma imagem enviada")

    next_index = len([img for img in product.images if img.image_type == ImageType.original]) + 1
    uploaded = []

    for file in files:
        if not (file.content_type or "").startswith("image/"):
            raise HTTPException(status_code=400, detail=f"Arquivo inválido: {file.filename}")

        filename = f"{product.oem}_original_{next_index}.jpg"

        image = Image(
            product_id=product.id,
            image_type=ImageType.original,
            sort_order=next_index,
            filename=filename,
            storage_path=f"local/dev/{filename}",
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
        "message": "Imagens registradas com sucesso",
        "files": uploaded,
    }