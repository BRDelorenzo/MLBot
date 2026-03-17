from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportItem, ItemStatus, Listing, ListingStatus, Product
from app.schemas import ListingOut, ValidationResponse

router = APIRouter(prefix="/products", tags=["listings"])


def generate_listing_title(product: Product) -> str:
    main_fitment = None
    if product.compatibilities:
        c = product.compatibilities[0]
        years = f"{c.year_start}-{c.year_end}" if c.year_start != c.year_end else str(c.year_start)
        main_fitment = f"Para {c.motorcycle_model} {years}"

    chunks = [
        product.part_name or "Peça de Moto",
        product.brand or "",
        product.oem,
        main_fitment or "",
    ]

    title = " ".join(chunk for chunk in chunks if chunk).strip()
    return title[:60]


def generate_listing_description(product: Product) -> str:
    compat_lines = []
    for comp in product.compatibilities:
        years = f"{comp.year_start} a {comp.year_end}" if comp.year_start != comp.year_end else str(comp.year_start)
        compat_lines.append(f"- {comp.motorcycle_brand} {comp.motorcycle_model} ({years})")

    attrs = []
    for attr in product.attributes:
        attrs.append(f"- {attr.name}: {attr.value}")

    return f"""
Peça: {product.part_name or 'Não informado'}
Marca: {product.brand or 'Não informada'}
OEM: {product.oem}
Categoria: {product.category or 'Não informada'}

Compatibilidade:
{chr(10).join(compat_lines) if compat_lines else '- Compatibilidade em revisão'}

Atributos técnicos:
{chr(10).join(attrs) if attrs else '- Sem atributos cadastrados'}

Importante:
- Confirme o código OEM antes da compra.
- Em caso de dúvida, consulte a aplicação da peça no manual da moto.
""".strip()


@router.post("/{product_id}/listing/generate", response_model=ListingOut)
def generate_listing(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    listing = product.listing
    if not listing:
        listing = Listing(product_id=product.id)
        db.add(listing)

    listing.title = generate_listing_title(product)
    listing.description = generate_listing_description(product)
    listing.ml_category = listing.ml_category or "MLB0000"
    listing.price = product.pricing.final_price if product.pricing else None
    listing.status = ListingStatus.draft

    db.commit()
    db.refresh(listing)
    return listing


@router.post("/{product_id}/listing/validate", response_model=ValidationResponse)
def validate_listing(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    errors = []
    if not product.part_name:
        errors.append("Nome da peça não preenchido")
    if not product.brand:
        errors.append("Marca não preenchida")
    if not product.category:
        errors.append("Categoria não definida")
    if not product.compatibilities:
        errors.append("Nenhuma compatibilidade cadastrada")
    if not product.images:
        errors.append("Nenhuma imagem enviada")
    if not product.listing or not product.listing.title:
        errors.append("Anúncio ainda não foi gerado")
    if not product.pricing or not product.pricing.final_price:
        errors.append("Preço ainda não foi calculado")

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()

    if errors:
        if product.listing:
            product.listing.status = ListingStatus.validation_error
        if import_item:
            import_item.status = ItemStatus.validation_error
        db.commit()
        return {"valid": False, "errors": errors}

    if product.listing:
        product.listing.status = ListingStatus.valid
    if import_item:
        import_item.status = ItemStatus.ready_to_publish

    db.commit()
    return {"valid": True, "errors": []}


@router.post("/{product_id}/listing/publish")
def publish_listing(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or not product.listing:
        raise HTTPException(status_code=404, detail="Anúncio não encontrado")

    if product.listing.status != ListingStatus.valid:
        raise HTTPException(status_code=400, detail="Anúncio precisa estar validado antes da publicação")

    # Simulação temporária da publicação
    simulated_ml_id = f"MLB{product.id:08d}"
    product.listing.ml_item_id = simulated_ml_id
    product.listing.status = ListingStatus.published

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
    if import_item:
        import_item.status = ItemStatus.published

    db.commit()

    return {
        "message": "Anúncio publicado com sucesso (simulado)",
        "ml_item_id": simulated_ml_id,
    }