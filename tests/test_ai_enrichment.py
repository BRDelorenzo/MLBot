import json
from io import BytesIO
from unittest.mock import MagicMock, patch


def _create_product(client, oem="AI-TEST-001"):
    content = oem.encode()
    client.post("/batches/import", files={"file": ("oems.txt", BytesIO(content), "text/plain")})
    return client.get("/products").json()[0]["id"]


def _mock_claude_response():
    """Retorna um mock de resposta do Claude."""
    return {
        "common_name": "Disco de Freio Dianteiro",
        "brand": "Honda",
        "category": "Freio",
        "technical_description": "Disco de freio dianteiro original Honda, fabricado em aço inoxidável.",
        "compatibilities": [
            {"motorcycle_brand": "Honda", "motorcycle_model": "CG 160 Titan", "year_start": 2018, "year_end": 2024},
            {"motorcycle_brand": "Honda", "motorcycle_model": "CG 160 Fan", "year_start": 2019, "year_end": 2024},
        ],
        "attributes": [
            {"name": "Material", "value": "Aço Inoxidável"},
            {"name": "Posição", "value": "Dianteiro"},
        ],
        "confidence": 85,
    }


def _setup_mock_provider(mock_call_llm, user_id):
    """Configura o mock do call_llm e registra um provider fake."""
    from app.services.ai_enrichment import set_provider_config

    set_provider_config(user_id, "anthropic", api_key="test-key-12345678901234", model="claude-sonnet-4-20250514")
    mock_call_llm.return_value = _mock_claude_response()


@patch("app.services.ai_enrichment.call_llm")
def test_ai_enrich_product(mock_call_llm, client, user_id):
    _setup_mock_provider(mock_call_llm, user_id)
    pid = _create_product(client, "53170-MEL-006")

    resp = client.post(f"/products/{pid}/ai-enrich")
    assert resp.status_code == 200
    data = resp.json()
    assert data["common_name"] == "Disco de Freio Dianteiro"
    assert data["confidence"] == 85
    assert data["source"] == "anthropic"
    assert data["provider"] == "Anthropic (Claude)"
    assert data["compatibilities_count"] == 2
    assert data["attributes_count"] == 2


@patch("app.services.ai_enrichment.call_llm")
def test_ai_enrich_updates_product(mock_call_llm, client, user_id):
    _setup_mock_provider(mock_call_llm, user_id)
    pid = _create_product(client, "AI-UPDATE-001")
    client.post(f"/products/{pid}/ai-enrich")

    product = client.get(f"/products/{pid}").json()
    assert product["part_name"] == "Disco de Freio Dianteiro"
    assert product["brand"] == "Honda"
    assert product["category"] == "Freio"
    assert product["confidence_level"] == 85
    assert product["source_data"] == "anthropic"
    assert len(product["compatibilities"]) == 2
    assert len(product["attributes"]) == 2


@patch("app.services.ai_enrichment.call_llm")
def test_ai_enrich_with_kb(mock_call_llm, client, db, user_id):
    """Quando o OEM está na KB, source deve conter 'kb+'."""
    _setup_mock_provider(mock_call_llm, user_id)

    from app.models import KBDocument, KBDocumentStatus, KBEntry

    doc = KBDocument(user_id=user_id, filename="test.pdf", storage_path="/tmp/test.pdf", status=KBDocumentStatus.processed)
    db.add(doc)
    db.flush()
    db.add(KBEntry(
        document_id=doc.id,
        oem_code="KB-OEM-001",
        oem_code_normalized="KB-OEM-001",
        honda_part_name="COMP., R. FR. BRAKE DISK",
    ))
    db.commit()

    pid = _create_product(client, "KB-OEM-001")
    resp = client.post(f"/products/{pid}/ai-enrich")
    assert resp.status_code == 200
    assert resp.json()["source"] == "kb+anthropic"


def test_ai_enrich_no_api_key(client):
    """Sem nenhum provider configurado deve dar erro."""
    from app.services.ai_enrichment import _provider_cache
    _provider_cache.clear()

    pid = _create_product(client, "NOKEY-001")
    resp = client.post(f"/products/{pid}/ai-enrich")
    assert resp.status_code == 500
    detail = resp.json()["detail"].lower()
    assert "api key" in detail or "configura" in detail or "provider" in detail


def test_ai_enrich_not_found(client):
    resp = client.post("/products/999/ai-enrich")
    assert resp.status_code == 404


@patch("app.services.ai_enrichment.call_llm")
def test_ai_enrich_replaces_previous_data(mock_call_llm, client, user_id):
    """AI enrich deve substituir dados anteriores (mock ou outro AI)."""
    _setup_mock_provider(mock_call_llm, user_id)

    pid = _create_product(client, "REPLACE-001")

    # Primeiro enriquece com mock
    client.post(f"/products/{pid}/mock-enrich")
    product = client.get(f"/products/{pid}").json()
    assert product["source_data"] == "mock_provider"

    # Depois com AI
    client.post(f"/products/{pid}/ai-enrich")
    product = client.get(f"/products/{pid}").json()
    assert product["source_data"] == "anthropic"
    assert product["part_name"] == "Disco de Freio Dianteiro"
    assert len(product["compatibilities"]) == 2


@patch("app.services.ai_enrichment.call_llm")
def test_ai_enrich_with_specific_provider(mock_call_llm, client, user_id):
    """Deve aceitar provider específico via query param."""
    from app.services.ai_enrichment import set_provider_config

    set_provider_config(user_id, "openai", api_key="sk-test-key-12345678901234", model="gpt-4o-mini")
    mock_call_llm.return_value = _mock_claude_response()

    pid = _create_product(client, "PROVIDER-001")
    resp = client.post(f"/products/{pid}/ai-enrich?provider=openai")
    assert resp.status_code == 200
    assert resp.json()["provider"] == "OpenAI (GPT)"
    assert resp.json()["source"] == "openai"
