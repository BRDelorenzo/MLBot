import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportItem, ItemStatus, Listing, ListingStatus, Product
from app.schemas import ListingOut, MLPublishResult, ValidationResponse
from app.services.mercadolivre import MLAPIError, get_category_attributes, get_valid_token, predict_category, publish_item, upload_image

logger = logging.getLogger(__name__)

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

    try:
        predicted = predict_category(listing.title)
        listing.ml_category = predicted["category_id"]
        logger.info("Categoria prevista para '%s': %s (%s)", listing.title, predicted["category_id"], predicted["category_name"])
    except MLAPIError as exc:
        logger.warning("Falha ao prever categoria para '%s': %s", listing.title, exc.detail)
        if not listing.ml_category:
            listing.ml_category = None

    listing.price = float(product.pricing.final_price) if product.pricing and product.pricing.final_price else None
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
    if product.listing and not product.listing.ml_category:
        errors.append("Categoria do ML não definida (gere o listing novamente)")
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


@router.post("/{product_id}/listing/publish", response_model=MLPublishResult)
def publish_listing(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or not product.listing:
        raise HTTPException(status_code=404, detail="Anúncio não encontrado")

    if product.listing.status != ListingStatus.valid:
        raise HTTPException(status_code=400, detail="Anúncio precisa estar validado antes da publicação")

    try:
        access_token = get_valid_token(db)
    except MLAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # Upload de imagens locais para o ML
    pictures = []
    for img in product.images:
        if img.storage_path.startswith("http"):
            pictures.append({"source": img.storage_path})
        elif img.storage_path:
            try:
                picture_id = upload_image(access_token, img.storage_path)
                pictures.append({"id": picture_id})
            except MLAPIError:
                logger.warning("Falha ao enviar imagem %s ao ML", img.storage_path)

    if not pictures:
        raise HTTPException(status_code=400, detail="Nenhuma imagem válida para publicar. Envie fotos do produto primeiro.")

    # Atributos obrigatórios: PART_NUMBER (OEM) e BRAND
    ml_attributes = [
        {"id": "PART_NUMBER", "value_name": product.oem},
        {"id": "BRAND", "value_name": product.brand or "Genérica"},
    ]

    # Busca atributos aceitos pela categoria e adiciona os compatíveis
    try:
        category_attrs = get_category_attributes(product.listing.ml_category)
        allowed_attr_ids = {a["id"] for a in category_attrs}
        attr_name_to_id = {a.get("name", "").lower(): a["id"] for a in category_attrs}
        already_added = {a["id"] for a in ml_attributes}

        for attr in product.attributes:
            attr_id = attr_name_to_id.get(attr.name.lower())
            if attr_id and attr_id in allowed_attr_ids and attr_id not in already_added:
                cat_attr = next((a for a in category_attrs if a["id"] == attr_id), None)
                if cat_attr and cat_attr.get("tags", {}).get("read_only"):
                    continue
                ml_attributes.append({"id": attr_id, "value_name": attr.value})

        if "SELLER_SKU" in allowed_attr_ids:
            ml_attributes.append({"id": "SELLER_SKU", "value_name": product.oem})
    except MLAPIError:
        logger.warning("Não foi possível buscar atributos da categoria %s", product.listing.ml_category)

    try:
        result = publish_item(
            access_token=access_token,
            title=product.listing.title,
            category_id=product.listing.ml_category,
            price=float(product.listing.price),
            currency_id="BRL",
            available_quantity=product.listing.quantity,
            buying_mode="buy_it_now",
            condition=product.listing.condition,
            listing_type_id="gold_special",
            description=product.listing.description,
            pictures=pictures,
            attributes=ml_attributes,
        )
    except MLAPIError as exc:
        product.listing.status = ListingStatus.publish_error
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    product.listing.ml_item_id = result["id"]
    product.listing.status = ListingStatus.published

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
    if import_item:
        import_item.status = ItemStatus.published

    db.commit()

    return MLPublishResult(
        ml_item_id=result["id"],
        permalink=result.get("permalink"),
        status="published",
    )
