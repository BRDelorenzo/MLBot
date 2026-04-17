"""Serviço de enriquecimento de produtos usando LLM + Base de Conhecimento.

Suporta múltiplos providers: Anthropic (Claude), OpenAI (GPT), Google (Gemini).
"""

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import (
    ImportItem,
    ItemStatus,
    KBEntry,
    Product,
    ProductAttribute,
    ProductCompatibility,
    ProductPricing,
)
from app.routers.batches import normalize_oem

logger = logging.getLogger(__name__)

# --- Provider Registry (in-memory) ---

PROVIDERS = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "models": [
            "claude-sonnet-4-20250514",
            "claude-haiku-4-5-20251001",
        ],
        "default_model": "claude-sonnet-4-20250514",
        "key_prefix": "sk-ant-",
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
        ],
        "default_model": "gpt-4o-mini",
        "key_prefix": "sk-",
    },
    "gemini": {
        "name": "Google (Gemini)",
        "models": [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
        ],
        "default_model": "gemini-2.5-flash",
        "key_prefix": "AI",
    },
}


@dataclass
class ProviderConfig:
    api_key: str = ""
    model: str = ""


# Cache em memória por (user_id, provider_id) com TTL curto.
# Multi-worker: worker A rotaciona key → worker B recarrega do DB em até PROVIDER_CACHE_TTL.
PROVIDER_CACHE_TTL = 60.0
_provider_cache: dict[tuple[int, str], tuple[float, ProviderConfig]] = {}


def _load_provider_from_db(user_id: int, provider_id: str, db: Session) -> ProviderConfig | None:
    """Carrega config do banco e descriptografa a API key."""
    from app.models import AIProviderConfig
    from app.services.crypto import decrypt

    row = (
        db.query(AIProviderConfig)
        .filter(AIProviderConfig.user_id == user_id, AIProviderConfig.provider_id == provider_id)
        .first()
    )
    if not row:
        return None
    import time as _t
    cfg = ProviderConfig(api_key=decrypt(row.api_key_encrypted), model=row.model)
    _provider_cache[(user_id, provider_id)] = (_t.time(), cfg)
    return cfg


def get_provider_config(user_id: int, provider_id: str, db: Session | None = None) -> ProviderConfig:
    import time as _t

    entry = _provider_cache.get((user_id, provider_id))
    if entry:
        ts, cfg = entry
        if cfg.api_key and (_t.time() - ts) < PROVIDER_CACHE_TTL:
            return cfg
    if db:
        loaded = _load_provider_from_db(user_id, provider_id, db)
        if loaded:
            return loaded
    return ProviderConfig()


def set_provider_config(user_id: int, provider_id: str, api_key: str, model: str | None = None, db: Session | None = None):
    if provider_id not in PROVIDERS:
        raise ValueError(f"Provider desconhecido: {provider_id}")
    if not model:
        model = PROVIDERS[provider_id]["default_model"]

    import time as _t
    cfg = ProviderConfig(api_key=api_key, model=model)
    _provider_cache[(user_id, provider_id)] = (_t.time(), cfg)

    if db:
        from app.models import AIProviderConfig
        from app.services.crypto import encrypt

        row = (
            db.query(AIProviderConfig)
            .filter(AIProviderConfig.user_id == user_id, AIProviderConfig.provider_id == provider_id)
            .first()
        )
        if row:
            row.api_key_encrypted = encrypt(api_key)
            row.model = model
        else:
            db.add(AIProviderConfig(
                user_id=user_id,
                provider_id=provider_id,
                api_key_encrypted=encrypt(api_key),
                model=model,
            ))
        db.commit()


def remove_provider_config(user_id: int, provider_id: str, db: Session | None = None):
    _provider_cache.pop((user_id, provider_id), None)
    if db:
        from app.models import AIProviderConfig
        row = (
            db.query(AIProviderConfig)
            .filter(AIProviderConfig.user_id == user_id, AIProviderConfig.provider_id == provider_id)
            .first()
        )
        if row:
            db.delete(row)
            db.commit()


def get_active_provider(user_id: int, db: Session | None = None) -> tuple[str, ProviderConfig] | None:
    """Retorna o primeiro provider configurado com API key para o usuário."""
    for pid in ("anthropic", "openai", "gemini"):
        cfg = get_provider_config(user_id, pid, db)
        if cfg and cfg.api_key:
            return pid, cfg
    return None


def get_all_provider_status(user_id: int, db: Session | None = None) -> list[dict]:
    """Retorna status de todos os providers para o usuário."""
    result = []
    for pid, info in PROVIDERS.items():
        cfg = get_provider_config(user_id, pid, db)
        has_key = bool(cfg.api_key)
        masked = ""
        if has_key:
            k = cfg.api_key
            masked = k[:8] + "..." + k[-4:] if len(k) > 12 else "***"
        result.append({
            "id": pid,
            "name": info["name"],
            "models": info["models"],
            "default_model": info["default_model"],
            "configured": has_key,
            "masked_key": masked,
            "selected_model": cfg.model or info["default_model"],
        })
    return result


def invalidate_provider_cache(user_id: int | None = None):
    """Invalida cache. Sem user_id, limpa tudo."""
    if user_id is None:
        _provider_cache.clear()
    else:
        for key in list(_provider_cache.keys()):
            if key[0] == user_id:
                _provider_cache.pop(key, None)


# --- Prompts ---

SYSTEM_PROMPT = """\
Você é um especialista em peças de motos Honda no mercado brasileiro.
Você recebe dados técnicos de catálogos Honda e deve traduzir para linguagem de marketplace.

REGRA CRÍTICA: Os catálogos Honda usam nomes técnicos em inglês abreviado.
Você DEVE encontrar o NOME POPULAR BRASILEIRO que compradores usam no Mercado Livre.
NÃO use o nome do catálogo Honda. Use o nome que as pessoas realmente buscam.

Exemplos de tradução:
- "COMP., R. FR. BRAKE DISK" → "Disco de Freio Dianteiro"
- "PAD SET, FR." → "Jogo de Pastilha de Freio Dianteira"
- "CABLE COMP., THROTTLE" → "Cabo de Acelerador"
- "LEVER COMP., R. HANDLE" → "Manete de Freio Dianteiro"
- "CHAIN SET" → "Kit Relação (Corrente, Coroa e Pinhão)"
- "PIPE COMP., EX." → "Escapamento"
- "ELEMENT COMP., AIR CLEANER" → "Filtro de Ar"
- "SPARK PLUG" → "Vela de Ignição"
- "SWITCH ASSY., WINKER" → "Interruptor de Seta / Pisca"
- "BULB, HEADLIGHT" → "Lâmpada do Farol"
- "GASKET SET A" → "Jogo de Juntas do Motor"
- "PISTON" → "Pistão do Motor"
- "BEARING, RADIAL BALL" → "Rolamento"
- "SPROCKET, DRIVE" → "Pinhão"
- "SPROCKET, DRIVEN" → "Coroa"
- "TIRE" → "Pneu"
- "TUBE, INNER" → "Câmara de Ar"
- "MIRROR COMP." → "Retrovisor"
- "FENDER, FR." → "Paralama Dianteiro"
- "SEAT COMP." �� "Banco"

Se o código OEM não estiver na base de conhecimento, use seu conhecimento geral sobre peças Honda.
Neste caso, diminua o confidence para 40-60.

IMPORTANTE: Responda APENAS com JSON válido, sem markdown, sem explicações.\
"""

USER_PROMPT_TEMPLATE = """\
Código OEM: {oem}
{kb_section}
Retorne um JSON com esta estrutura exata:
{{
  "common_name": "Nome popular brasileiro da peça (como buscam no Mercado Livre)",
  "brand": "Honda",
  "category": "Categoria da peça (ex: Freio, Motor, Transmissão, Elétrica, Suspensão, Escapamento, Carenagem, Iluminação)",
  "technical_description": "Descrição completa em português para anúncio no Mercado Livre. 2-3 frases descrevendo a peça, material, aplicação.",
  "compatibilities": [
    {{"motorcycle_brand": "Honda", "motorcycle_model": "Nome do modelo", "year_start": 2018, "year_end": 2024}}
  ],
  "attributes": [
    {{"name": "Nome do atributo (use nomes do Mercado Livre: Tipo de parafuso, Material, Posição, etc.)", "value": "Valor"}}
  ],
  "confidence": 85
}}\
"""


# --- LLM Calls por Provider ---

def _clean_json_response(raw_text: str) -> dict:
    """Remove markdown fences e parseia JSON."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    return json.loads(text)


def _call_anthropic(api_key: str, model: str, system_prompt: str, user_prompt: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return _clean_json_response(response.content[0].text)


def _call_openai(api_key: str, model: str, system_prompt: str, user_prompt: str) -> dict:
    import openai

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return _clean_json_response(response.choices[0].message.content)


def _call_gemini(api_key: str, model: str, system_prompt: str, user_prompt: str) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    gen_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_prompt,
    )
    response = gen_model.generate_content(user_prompt)
    return _clean_json_response(response.text)


_CALL_FUNCTIONS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


def call_llm(provider_id: str, config: ProviderConfig, system_prompt: str, user_prompt: str) -> dict:
    """Chama o LLM do provider selecionado."""
    call_fn = _CALL_FUNCTIONS.get(provider_id)
    if not call_fn:
        raise ValueError(f"Provider não suportado: {provider_id}")
    return call_fn(config.api_key, config.model, system_prompt, user_prompt)


# --- KB Lookup ---

def _build_kb_section(kb_entries: list[KBEntry]) -> str:
    if not kb_entries:
        return "Base de Conhecimento: Nenhuma entrada encontrada para este OEM. Use seu conhecimento geral."

    parts = ["Dados da Base de Conhecimento (catálogo Honda):"]
    for entry in kb_entries:
        parts.append(f"\n--- Entrada (pág. {entry.page_number or '?'}) ---")
        if entry.honda_part_name:
            parts.append(f"Descrição Honda: {entry.honda_part_name}")
        if entry.honda_price:
            parts.append(f"Preço Honda (custo): R$ {entry.honda_price}")
        if entry.raw_text_block:
            parts.append(f"Contexto:\n{entry.raw_text_block}")

    return "\n".join(parts)


def _get_honda_price(kb_entries: list[KBEntry]) -> float | None:
    """Retorna o preço Honda do primeiro entry que tenha preço."""
    for entry in kb_entries:
        if entry.honda_price:
            return float(entry.honda_price)
    return None


def lookup_kb(oem: str, db: Session, user_id: int | None = None) -> list[KBEntry]:
    from app.models import KBDocument

    normalized = normalize_oem(oem)
    query = (
        db.query(KBEntry)
        .join(KBDocument, KBEntry.document_id == KBDocument.id)
        .filter(KBEntry.oem_code_normalized == normalized)
    )
    if user_id is not None:
        query = query.filter(KBDocument.user_id == user_id)
    return query.all()


# --- Enrichment ---

def _apply_enrichment(product: Product, enrichment: dict, source: str, db: Session):
    product.part_name = enrichment.get("common_name") or product.part_name
    product.brand = enrichment.get("brand") or product.brand or "Honda"
    product.category = enrichment.get("category") or product.category
    product.technical_description = enrichment.get("technical_description") or product.technical_description
    product.confidence_level = enrichment.get("confidence", 50)
    product.source_data = source

    for c in list(product.compatibilities):
        db.delete(c)

    for compat in enrichment.get("compatibilities", []):
        product.compatibilities.append(ProductCompatibility(
            motorcycle_brand=compat.get("motorcycle_brand", "Honda"),
            motorcycle_model=compat["motorcycle_model"],
            year_start=compat.get("year_start", 2020),
            year_end=compat.get("year_end", 2025),
            notes=None,
        ))

    for a in list(product.attributes):
        db.delete(a)

    for attr in enrichment.get("attributes", []):
        if attr.get("name") and attr.get("value"):
            product.attributes.append(ProductAttribute(
                name=attr["name"],
                value=attr["value"],
            ))


def _auto_pricing(product: Product, cost: float, db: Session):
    """Cria/atualiza pricing automaticamente usando o custo Honda."""
    from app.routers.products import calculate_suggested_price

    commission = 0.16
    margin = 0.20
    shipping = 0.0
    fee = 0.0

    suggested = calculate_suggested_price(cost, shipping, commission, fee, margin)

    pricing = product.pricing
    if not pricing:
        pricing = ProductPricing(product_id=product.id, cost=cost)
        db.add(pricing)

    pricing.cost = cost
    pricing.estimated_shipping = shipping
    pricing.commission_percent = commission
    pricing.fixed_fee = fee
    pricing.margin_percent = margin
    pricing.suggested_price = suggested
    pricing.final_price = suggested


def enrich_product(product: Product, db: Session, provider_id: str | None = None) -> dict:
    """Enriquece um produto usando KB + LLM.

    Se provider_id não for especificado, usa o primeiro provider configurado.
    """
    if not product.user_id:
        raise RuntimeError("Produto sem user_id não pode ser enriquecido.")

    # Resolve provider (isolado por usuário)
    if provider_id:
        cfg = get_provider_config(product.user_id, provider_id, db)
        if not cfg.api_key:
            raise RuntimeError(f"API Key do provider '{provider_id}' não configurada. Vá em Base de Conhecimento > Configuração da IA.")
    else:
        active = get_active_provider(product.user_id, db)
        if not active:
            raise RuntimeError(
                "Nenhuma API Key configurada. "
                "Vá em Base de Conhecimento > Configuração da IA e adicione pelo menos uma chave."
            )
        provider_id, cfg = active

    provider_name = PROVIDERS[provider_id]["name"]

    # 1. Busca na base de conhecimento
    kb_entries = lookup_kb(product.oem, db, user_id=product.user_id)
    source = f"kb+{provider_id}" if kb_entries else provider_id

    # 2. Monta o prompt
    kb_section = _build_kb_section(kb_entries)
    user_prompt = USER_PROMPT_TEMPLATE.format(oem=product.oem, kb_section=kb_section)

    # 3. Chama o LLM
    logger.info("Enriquecendo produto %d (OEM: %s) via %s [%s]", product.id, product.oem, provider_name, cfg.model)
    enrichment = call_llm(provider_id, cfg, SYSTEM_PROMPT, user_prompt)

    # 4-6. Aplica tudo em transação atômica
    honda_price = _get_honda_price(kb_entries)
    try:
        _apply_enrichment(product, enrichment, source, db)

        if honda_price:
            _auto_pricing(product, honda_price, db)

        import_item = db.query(ImportItem).filter(ImportItem.id == product.import_item_id).first()
        if import_item:
            import_item.status = ItemStatus.awaiting_review

        db.commit()
        db.refresh(product)
    except Exception:
        db.rollback()
        raise

    return {
        "product_id": product.id,
        "common_name": enrichment.get("common_name", ""),
        "confidence": enrichment.get("confidence", 0),
        "source": source,
        "provider": provider_name,
        "model": cfg.model,
        "honda_price": honda_price,
        "compatibilities_count": len(product.compatibilities),
        "attributes_count": len(product.attributes),
    }
