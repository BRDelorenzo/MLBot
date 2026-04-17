import logging
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models import ImportItem, ItemStatus, Listing, ListingStatus, Product, PublishEvent, User, UserRole
from app.services.auth import get_current_user, require_role
from app.schemas import ListingOut, MLPublishResult, ValidationResponse
from app.services.ai_enrichment import lookup_kb
from app.services.mercadolivre import (
    MLAPIError,
    get_category_attributes,
    get_valid_token,
    predict_category,
    publish_item,
    search_item_by_seller_sku,
    upload_image,
)
from app.models import MLCredential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/products", tags=["listings"])


def _match_ml_value(product_value: str, cat_attr: dict) -> str | None:
    """Valida/mapeia o valor do produto para um valor aceito pelo ML.

    Se o atributo tem lista de valores permitidos, faz match exato ou parcial.
    Se não tem lista (texto livre), retorna o valor direto.
    """
    allowed_values = cat_attr.get("values", [])
    if not allowed_values:
        # Atributo de texto livre — aceita qualquer valor
        return product_value

    val_lower = product_value.lower().strip()

    # Match exato
    for av in allowed_values:
        if av.get("name", "").lower() == val_lower:
            return av["name"]

    # Match parcial: valor do produto contido no valor ML ou vice-versa
    for av in allowed_values:
        av_name = av.get("name", "").lower()
        if val_lower in av_name or av_name in val_lower:
            return av["name"]

    # Nenhum match — pula este atributo para não causar erro na publicação
    logger.warning(
        "Valor '%s' não aceito para atributo '%s' (ID: %s). Valores válidos: %s",
        product_value, cat_attr.get("name"), cat_attr["id"],
        [v["name"] for v in allowed_values[:10]],
    )
    return None


def _check_missing_required_attrs(product: Product) -> list[str]:
    """Retorna nomes de atributos obrigatórios da categoria ML que faltam no produto."""
    if not product.listing or not product.listing.ml_category:
        return []

    category_attrs = get_category_attributes(product.listing.ml_category)
    product_attr_names = {a.name.lower() for a in product.attributes}

    # Atributos que já preenchemos automaticamente na publicação
    auto_filled = {"PART_NUMBER", "BRAND", "MODEL", "SELLER_SKU"}

    missing = []
    for cat_attr in category_attrs:
        attr_id = cat_attr["id"]
        tags = cat_attr.get("tags", {})
        if tags.get("read_only"):
            continue
        if not (tags.get("required") or tags.get("catalog_required")):
            continue
        if attr_id in auto_filled:
            continue
        # Verifica se o produto tem um atributo com nome compatível
        attr_name = cat_attr.get("name", "").lower()
        attr_name_to_id_match = attr_name in product_attr_names or attr_id.lower().replace("_", " ") in product_attr_names
        if not attr_name_to_id_match:
            missing.append(cat_attr.get("name", attr_id))
    return missing


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


def generate_listing_description(product: Product, honda_description: str | None = None) -> str:
    compat_lines = []
    for comp in product.compatibilities:
        years = f"{comp.year_start} a {comp.year_end}" if comp.year_start != comp.year_end else str(comp.year_start)
        compat_lines.append(f"- {comp.motorcycle_brand} {comp.motorcycle_model} ({years})")

    attrs = []
    for attr in product.attributes:
        attrs.append(f"- {attr.name}: {attr.value}")

    tech_desc = ""
    if product.technical_description:
        tech_desc = f"\nDescrição:\n{product.technical_description}\n"

    honda_desc = ""
    if honda_description:
        honda_desc = f"\nDescrição Honda (catálogo):\n{honda_description}\n"

    return f"""
Peça: {product.part_name or 'Não informado'}
Marca: {product.brand or 'Não informada'}
OEM: {product.oem}
Categoria: {product.category or 'Não informada'}
{tech_desc}{honda_desc}
Compatibilidade:
{chr(10).join(compat_lines) if compat_lines else '- Compatibilidade em revisão'}

Atributos técnicos:
{chr(10).join(attrs) if attrs else '- Sem atributos cadastrados'}

Importante:
- Confirme o código OEM antes da compra.
- Em caso de dúvida, consulte a aplicação da peça no manual da moto.
""".strip()


@router.post("/{product_id}/listing/generate", response_model=ListingOut)
def generate_listing(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id, Product.user_id == user.id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    listing = product.listing
    if not listing:
        listing = Listing(product_id=product.id)
        db.add(listing)

    listing.title = generate_listing_title(product)

    # Busca descrição Honda na base de conhecimento
    honda_description = None
    kb_entries = lookup_kb(product.oem, db, user_id=product.user_id)
    if kb_entries:
        honda_description = kb_entries[0].honda_part_name

    listing.description = generate_listing_description(product, honda_description=honda_description)

    try:
        predicted = predict_category(listing.title)
        listing.ml_category = predicted["category_id"]
        logger.info("Categoria prevista para '%s': %s (%s)", listing.title, predicted["category_id"], predicted["category_name"])
    except MLAPIError as exc:
        logger.warning("Falha ao prever categoria para '%s': %s", listing.title, exc.detail)
        if not listing.ml_category:
            listing.ml_category = None

    # Verifica atributos obrigatórios da categoria e adiciona faltantes ao produto
    if listing.ml_category:
        try:
            category_attrs = get_category_attributes(listing.ml_category)
            product_attr_names = {a.name.lower() for a in product.attributes}

            auto_filled = {"PART_NUMBER", "BRAND", "MODEL", "SELLER_SKU"}
            missing_attrs = []

            for cat_attr in category_attrs:
                attr_id = cat_attr["id"]
                tags = cat_attr.get("tags", {})
                if tags.get("read_only") or attr_id in auto_filled:
                    continue
                if not (tags.get("required") or tags.get("catalog_required")):
                    continue

                attr_name = cat_attr.get("name", "")
                id_as_name = attr_id.lower().replace("_", " ")
                if attr_name.lower() not in product_attr_names and id_as_name not in product_attr_names:
                    missing_attrs.append({"id": attr_id, "name": attr_name, "values": cat_attr.get("values", [])})

            # Adiciona atributos faltantes com valores da lista do ML (primeiro valor disponível)
            from app.models import ProductAttribute
            for ma in missing_attrs:
                value = None
                if ma["values"]:
                    value = ma["values"][0].get("name", "")
                if value:
                    product.attributes.append(ProductAttribute(name=ma["name"], value=value))
                    logger.info("Atributo '%s' adicionado automaticamente com valor '%s'", ma["name"], value)

        except MLAPIError:
            logger.warning("Não foi possível buscar atributos da categoria %s", listing.ml_category)

    listing.price = float(product.pricing.final_price) if product.pricing and product.pricing.final_price else None
    listing.status = ListingStatus.draft

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
    if import_item and import_item.status not in (
        ItemStatus.validating,
        ItemStatus.ready_to_publish,
        ItemStatus.publishing,
        ItemStatus.published,
    ):
        import_item.status = ItemStatus.validating

    db.commit()
    db.refresh(listing)
    return listing


@router.post("/{product_id}/listing/validate", response_model=ValidationResponse)
def validate_listing(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id, Product.user_id == user.id).first()
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

    # ml_category pode ter ficado vazio se o predict_category falhou no momento
    # de gerar o listing. Tenta resolver agora — evita forçar re-clique em Gerar.
    if product.listing and product.listing.title and not product.listing.ml_category:
        try:
            predicted = predict_category(product.listing.title)
            product.listing.ml_category = predicted.get("category_id") or None
            if product.listing.ml_category:
                logger.info(
                    "Categoria do ML resolvida durante validação para '%s': %s",
                    product.listing.title, product.listing.ml_category,
                )
        except MLAPIError as exc:
            logger.warning(
                "predict_category falhou durante validação (title='%s'): %s",
                product.listing.title, exc.detail,
            )

    if product.listing and not product.listing.ml_category:
        errors.append(
            "Não foi possível determinar a categoria do ML para este título. "
            "Refine o nome da peça no enriquecimento ou gere o anúncio novamente."
        )
    if not product.pricing or not product.pricing.final_price:
        errors.append("Preço ainda não foi calculado")

    # Verifica atributos obrigatórios da categoria ML.
    # Fail-closed: se o ML não responde, a validação falha — caso contrário
    # o publish descobre tarde demais que faltam atributos.
    if product.listing and product.listing.ml_category:
        try:
            missing = _check_missing_required_attrs(product)
            for attr_name in missing:
                errors.append(f"Atributo obrigatório do ML faltando: \"{attr_name}\" — adicione via enriquecimento IA ou edite manualmente")
        except MLAPIError as exc:
            logger.warning("Falha ao buscar atributos da categoria %s durante validação: %s", product.listing.ml_category, exc.detail)
            errors.append("Não foi possível verificar atributos obrigatórios (ML indisponível). Tente novamente em instantes.")

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


_REDACT_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)access_token[\"'\s:=]+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)refresh_token[\"'\s:=]+[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
]


def _redact(text: str) -> str:
    for rx in _REDACT_PATTERNS:
        text = rx.sub("[REDACTED]", text)
    return text


def _log_publish_event(listing_id: int, user_id: int, idempotency_key: str,
                       phase: str, ml_item_id: str | None = None, detail: str | None = None):
    """Escreve PublishEvent em sessão própria — nunca parte da transação principal.

    Garante que o evento persiste mesmo se a transação do publish falhar no
    commit. Usado para reconciliação manual.
    """
    db = SessionLocal()
    try:
        safe_detail = _redact(detail or "")[:4000]
        db.add(PublishEvent(
            listing_id=listing_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            phase=phase,
            ml_item_id=ml_item_id,
            detail=safe_detail,
        ))
        db.commit()
    except Exception:
        logger.exception("Falha ao registrar PublishEvent")
        db.rollback()
    finally:
        db.close()


@router.get("/{product_id}/listing/required-attributes")
def get_required_attributes(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Retorna atributos obrigatórios da categoria ML e quais estão faltando no produto.

    Frontend usa para destacar campos antes do usuário tentar validar/publicar.
    """
    product = db.query(Product).filter(Product.id == product_id, Product.user_id == user.id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    if not product.listing or not product.listing.ml_category:
        return {"category_id": None, "required": [], "missing": [], "available": False}

    try:
        category_attrs = get_category_attributes(product.listing.ml_category)
    except MLAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    product_attr_names = {a.name.lower() for a in product.attributes}
    auto_filled = {"PART_NUMBER", "BRAND", "MODEL", "SELLER_SKU"}

    required = []
    missing = []
    for cat_attr in category_attrs:
        attr_id = cat_attr["id"]
        tags = cat_attr.get("tags", {})
        if tags.get("read_only") or attr_id in auto_filled:
            continue
        if not (tags.get("required") or tags.get("catalog_required")):
            continue
        attr_name = cat_attr.get("name", attr_id)
        required.append({
            "id": attr_id,
            "name": attr_name,
            "values": [v.get("name") for v in cat_attr.get("values", [])[:20]],
        })
        id_as_name = attr_id.lower().replace("_", " ")
        if attr_name.lower() not in product_attr_names and id_as_name not in product_attr_names:
            missing.append(attr_name)

    return {
        "category_id": product.listing.ml_category,
        "required": required,
        "missing": missing,
        "available": True,
    }


@router.post("/{product_id}/listing/publish", response_model=MLPublishResult)
def publish_listing(product_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.admin, UserRole.operator))):
    product = db.query(Product).filter(Product.id == product_id, Product.user_id == user.id).first()
    if not product or not product.listing:
        raise HTTPException(status_code=404, detail="Anúncio não encontrado")

    listing = product.listing

    if listing.status not in (ListingStatus.valid, ListingStatus.publish_error):
        raise HTTPException(status_code=400, detail="Anúncio precisa estar validado antes da publicação")

    # Idempotência: se já publicou com sucesso, retorna o mesmo ml_item_id.
    if listing.status == ListingStatus.published and listing.ml_item_id:
        return MLPublishResult(
            ml_item_id=listing.ml_item_id,
            permalink=None,
            status="already_published",
        )

    try:
        access_token = get_valid_token(db, user_id=user.id)
    except MLAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # Idempotency key nova por tentativa (mas só muda se não há uma em curso)
    idempotency_key = listing.idempotency_key or secrets.token_hex(16)

    # Detecção de duplicata: busca no ML por seller_sku (OEM) antes de publicar.
    # Cobre o caso de retry após ML ter aceitado o item mas commit local ter falhado.
    credential = db.query(MLCredential).filter(MLCredential.user_id == user.id).first()
    seller_id = credential.ml_user_id if credential else None
    if seller_id:
        try:
            duplicates = search_item_by_seller_sku(access_token, seller_id, product.oem)
            if duplicates:
                ml_item_id = duplicates[0]
                listing.ml_item_id = ml_item_id
                listing.status = ListingStatus.published
                listing.idempotency_key = None
                db.commit()
                _log_publish_event(
                    listing.id, user.id, idempotency_key,
                    "duplicate_detected", ml_item_id=ml_item_id,
                    detail=f"Item já existia no ML para seller_sku={product.oem}",
                )
                return MLPublishResult(
                    ml_item_id=ml_item_id,
                    permalink=None,
                    status="already_published",
                )
        except Exception:
            logger.exception("Falha ao checar duplicata por seller_sku — seguindo com publish")

    # Marca início da tentativa — persiste ANTES do call ao ML
    listing.status = ListingStatus.publishing
    listing.idempotency_key = idempotency_key
    listing.publish_attempts = (listing.publish_attempts or 0) + 1
    db.commit()
    _log_publish_event(listing.id, user.id, idempotency_key, "before_ml")

    # Upload de imagens — prioriza processadas (fundo branco), fallback para originais
    from app.models import ImageType
    processed = {img.sort_order: img for img in product.images if img.image_type == ImageType.processed}
    originals = {img.sort_order: img for img in product.images if img.image_type == ImageType.original}

    # Mescla: usa processada quando disponível, original caso contrário
    all_orders = sorted(set(list(processed.keys()) + list(originals.keys())))
    images_to_upload = [processed.get(order) or originals.get(order) for order in all_orders]

    pictures = []
    for img in images_to_upload:
        if not img:
            continue
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

    # MODEL: usa o primeiro modelo compatível (ex: "CG 160 Titan")
    if product.compatibilities:
        ml_attributes.append({"id": "MODEL", "value_name": product.compatibilities[0].motorcycle_model})

    # Busca atributos aceitos pela categoria e preenche required + compatíveis
    try:
        category_attrs = get_category_attributes(product.listing.ml_category)
        already_added = {a["id"] for a in ml_attributes}

        # Mapeamento: nome ML (lower) → ID, e ID (lower com _ → espaço) → ID
        attr_name_to_id = {}
        for ca in category_attrs:
            attr_name_to_id[ca.get("name", "").lower()] = ca["id"]
            # Ex: "SCREW_TYPE" → "tipo de parafuso" pode estar nos atributos do produto
            attr_name_to_id[ca["id"].lower().replace("_", " ")] = ca["id"]

        # Mapeia atributos do produto para atributos da categoria ML
        for attr in product.attributes:
            attr_id = attr_name_to_id.get(attr.name.lower())
            if attr_id and attr_id not in already_added:
                cat_attr = next((a for a in category_attrs if a["id"] == attr_id), None)
                if cat_attr and cat_attr.get("tags", {}).get("read_only"):
                    continue
                value = _match_ml_value(attr.value, cat_attr)
                if value:
                    ml_attributes.append({"id": attr_id, "value_name": value})
                    already_added.add(attr_id)

        # Preenche atributos obrigatórios faltantes com valores padrão ou valor do produto
        for cat_attr in category_attrs:
            attr_id = cat_attr["id"]
            tags = cat_attr.get("tags", {})
            if tags.get("read_only") or attr_id in already_added:
                continue
            if tags.get("required") or tags.get("catalog_required"):
                # Tenta preencher com valor padrão da categoria
                default_value = cat_attr.get("default_value")
                if default_value:
                    ml_attributes.append({"id": attr_id, "value_name": default_value})
                    already_added.add(attr_id)

        if "SELLER_SKU" not in already_added:
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
        _log_publish_event(
            listing.id, user.id, idempotency_key, "ml_error",
            detail=f"{exc.status_code}: {exc.detail}",
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # ML aceitou. Registra evento ANTES de tentar commit local — assim se o commit
    # falhar ainda temos rastro do ml_item_id para reconciliação.
    ml_item_id = result["id"]
    _log_publish_event(
        listing.id, user.id, idempotency_key, "ml_success",
        ml_item_id=ml_item_id, detail=result.get("permalink", ""),
    )

    try:
        product.listing.ml_item_id = ml_item_id
        product.listing.status = ListingStatus.published
        product.listing.idempotency_key = None

        import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
        if import_item:
            import_item.status = ItemStatus.published

        db.commit()
    except Exception as exc:
        db.rollback()
        _log_publish_event(
            listing.id, user.id, idempotency_key, "db_error",
            ml_item_id=ml_item_id,
            detail=f"DB commit falhou pós-publish: {exc!r}",
        )
        logger.exception("ML aceitou item %s mas DB commit falhou — ver PublishEvent para reconciliação", ml_item_id)
        raise HTTPException(
            status_code=500,
            detail=f"Anúncio criado no ML ({ml_item_id}) mas salvamento local falhou. Contate o suporte.",
        ) from exc

    return MLPublishResult(
        ml_item_id=ml_item_id,
        permalink=result.get("permalink"),
        status="published",
    )
