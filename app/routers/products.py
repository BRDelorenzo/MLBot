import logging
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.models import (
    EnrichJob,
    EnrichJobStatus,
    Image,
    ImageAccessToken,
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
from app.services.auth import get_current_user
from app.services.enrich_jobs import enqueue_bulk_enrich
from app.services.image_processing import remove_background

from datetime import timedelta

IMAGE_TOKEN_TTL_SECONDS = 300

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/products", tags=["products"])

MAX_IMAGE_BYTES = settings.max_image_size_mb * 1024 * 1024
MAX_IMAGES_PER_REQUEST = 10


def _get_user_product(
    product_id: int, db: Session, user: User, *, eager: bool = False,
) -> Product:
    """Busca produto garantindo que pertence ao usuário autenticado."""
    query = db.query(Product)
    if eager:
        query = query.options(
            joinedload(Product.import_item),
            joinedload(Product.compatibilities),
            joinedload(Product.attributes),
            joinedload(Product.images),
            joinedload(Product.pricing),
            joinedload(Product.listing),
        )
    product = query.filter(Product.id == product_id, Product.user_id == user.id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return product


def _ensure_upload_dir(user_id: int, product_oem: str) -> Path:
    """Isolamento multi-tenant: uploads/{user_id}/{oem}/.

    OEMs são compartilhados entre clientes (mesmo número Honda), então só
    separar por OEM permite sobrescrita cross-tenant. user_id no path é
    obrigatório.
    """
    safe_oem = Path(product_oem).name  # previne traversal
    path = Path(settings.upload_dir) / str(user_id) / safe_oem
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
    user: User = Depends(get_current_user),
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
        .filter(Product.user_id == user.id)
    )
    if status:
        query = query.filter(ImportItem.status == status)
    return query.order_by(Product.id.desc()).all()


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _get_user_product(product_id, db, user, eager=True)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    product = _get_user_product(product_id, db, user)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/mock-enrich", response_model=ProductOut)
def mock_enrich_product(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    product = _get_user_product(product_id, db, user)

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
    product = _get_user_product(product_id, db, user)

    import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
    if import_item:
        import_item.status = ItemStatus.enriching
        db.commit()

    try:
        result = ai_enrich(product, db, provider_id=provider)
    except RuntimeError as exc:
        logger.exception("Erro de runtime no enriquecimento do produto %s", product_id)
        raise HTTPException(status_code=500, detail="Erro no enriquecimento. Verifique a configuração do provider.") from exc
    except Exception as exc:
        logger.exception("Erro inesperado no enriquecimento IA do produto %s", product_id)
        if import_item:
            import_item.status = ItemStatus.imported
            db.commit()
        raise HTTPException(status_code=500, detail="Erro interno no enriquecimento. Tente novamente.") from exc

    return result


@router.post("/bulk-enrich")
def bulk_ai_enrich(batch_id: int = Query(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Enfileira enriquecimento em background e retorna job_id para polling."""
    from app.models import ImportBatch
    batch = db.query(ImportBatch).filter(ImportBatch.id == batch_id, ImportBatch.user_id == user.id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    items = (
        db.query(ImportItem)
        .filter(ImportItem.batch_id == batch_id)
        .filter(ImportItem.status.in_([ItemStatus.imported, ItemStatus.normalized]))
        .all()
    )

    if not items:
        raise HTTPException(status_code=404, detail="Nenhum item pendente para enriquecer neste lote")

    job = EnrichJob(
        user_id=user.id,
        batch_id=batch_id,
        status=EnrichJobStatus.queued,
        total=len(items),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    enqueue_bulk_enrich(job.id)

    return {
        "job_id": job.id,
        "status": job.status.value,
        "total": job.total,
    }


@router.get("/{product_id}/pricing/info")
def get_pricing_info(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Retorna dados de pricing existentes + preço Honda da KB."""
    product = _get_user_product(product_id, db, user)

    honda_price = None
    kb_entries = lookup_kb(product.oem, db, user_id=user.id)
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
    product = _get_user_product(product_id, db, user)

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
    product = _get_user_product(product_id, db, user)

    if not files:
        raise HTTPException(status_code=400, detail="Nenhuma imagem enviada")

    if len(files) > MAX_IMAGES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_IMAGES_PER_REQUEST} imagens por vez")

    upload_dir = _ensure_upload_dir(user.id, product.oem)
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


@router.delete("/{product_id}/images/{image_id}")
def delete_product_image(
    product_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove uma imagem do produto. Defense-in-depth: só deleta dentro de upload_dir."""
    product = _get_user_product(product_id, db, user)

    image = next((img for img in product.images if img.id == image_id), None)
    if not image:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")

    upload_root = Path(settings.upload_dir).resolve()
    try:
        file_path = Path(image.storage_path).resolve()
        safe = file_path.is_relative_to(upload_root)
    except (OSError, ValueError):
        safe = False

    if safe and file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            logger.exception("Falha ao remover arquivo de imagem id=%s path=%s", image.id, file_path)
    elif not safe:
        logger.error(
            "Tentativa de deletar imagem fora de upload_dir: id=%s path=%s",
            image.id, image.storage_path,
        )

    db.delete(image)
    db.commit()
    return {"message": "Imagem removida", "id": image_id}


@router.post("/{product_id}/images/process-background")
def process_images_background(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Remove o fundo de todas as imagens originais e gera versões com fundo branco."""
    product = _get_user_product(product_id, db, user)

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
    upload_dir = _ensure_upload_dir(user.id, product.oem)

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


@router.post("/{product_id}/images/access-token")
def create_image_access_token(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Emite um token short-lived para usar em <img src="...?access=xxx">.

    Mantém o JWT longo no Authorization header, não na URL (onde vazaria em
    logs de proxy/browser/referer).
    """
    product = _get_user_product(product_id, db, user)

    token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(seconds=IMAGE_TOKEN_TTL_SECONDS)
    db.add(
        ImageAccessToken(
            token=token,
            user_id=user.id,
            product_id=product.id,
            expires_at=expires_at,
        )
    )
    db.commit()
    return {"access_token": token, "expires_in": IMAGE_TOKEN_TTL_SECONDS}


@router.get("/{product_id}/images/{filename}")
def serve_product_image(
    product_id: int,
    filename: str,
    access: str | None = Query(default=None, alias="access"),
    db: Session = Depends(get_db),
):
    """Serve imagens com token short-lived (uma passagem).

    Fluxo:
      1. Cliente chama POST /products/{id}/images/access-token (JWT no header)
      2. Recebe access token e monta <img src="?access=...">
      3. Este endpoint valida, marca usado e serve o arquivo.
    """
    if not access:
        raise HTTPException(status_code=401, detail="Token de acesso à imagem obrigatório")

    now = utcnow()
    record = (
        db.query(ImageAccessToken)
        .filter(ImageAccessToken.token == access)
        .first()
    )
    if not record:
        raise HTTPException(status_code=401, detail="Token inválido")
    # Token é reutilizável dentro do TTL (5 min). Grid com N imagens precisa
    # servir N requests com um único token — ainda é user+product scoped.
    if record.expires_at <= now:
        raise HTTPException(status_code=401, detail="Token expirado")
    if record.product_id != product_id:
        raise HTTPException(status_code=403, detail="Token não corresponde ao produto solicitado")

    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == record.user_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    safe_name = Path(filename).name  # previne path traversal
    safe_oem = Path(product.oem).name
    file_path = Path(settings.upload_dir) / str(product.user_id) / safe_oem / safe_name
    # Fallback para estrutura antiga (pré-migração) — remove após rodar o script
    if not file_path.exists():
        legacy_path = Path(settings.upload_dir) / safe_oem / safe_name
        if legacy_path.exists():
            file_path = legacy_path
        else:
            raise HTTPException(status_code=404, detail="Imagem não encontrada")

    # used_at mantido para telemetria/auditoria — não bloqueia reuso.
    if record.used_at is None:
        record.used_at = now
        db.commit()

    return FileResponse(file_path)
