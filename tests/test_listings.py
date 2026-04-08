from io import BytesIO
from unittest.mock import patch


def _create_enriched_product(client, oem="LIST-001"):
    """Cria um produto enriquecido com pricing e imagem mockada."""
    content = oem.encode()
    client.post("/batches/import", files={"file": ("oems.txt", BytesIO(content), "text/plain")})
    pid = client.get("/products").json()[0]["id"]
    client.post(f"/products/{pid}/mock-enrich")
    client.post(f"/products/{pid}/pricing/calculate", json={"cost": 50.0, "fixed_fee": 6.0})
    return pid


def test_generate_listing(client):
    pid = _create_enriched_product(client)

    with patch("app.routers.listings.predict_category") as mock_cat:
        mock_cat.return_value = {"category_id": "MLB12345", "category_name": "Freios"}
        resp = client.post(f"/products/{pid}/listing/generate")

    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] is not None
    assert len(data["title"]) <= 60
    assert data["description"] is not None
    assert data["ml_category"] == "MLB12345"
    assert data["status"] == "draft"


def test_generate_listing_without_category(client):
    pid = _create_enriched_product(client)

    from app.services.mercadolivre import MLAPIError

    with patch("app.routers.listings.predict_category", side_effect=MLAPIError(500, "API down")):
        resp = client.post(f"/products/{pid}/listing/generate")

    assert resp.status_code == 200
    assert resp.json()["ml_category"] is None


def test_generate_listing_not_found(client):
    resp = client.post("/products/999/listing/generate")
    assert resp.status_code == 404


def test_validate_listing_missing_fields(client):
    """Produto recem importado (sem enriquecer) deve falhar validacao."""
    content = b"VAL-RAW-001"
    client.post("/batches/import", files={"file": ("oems.txt", BytesIO(content), "text/plain")})
    pid = client.get("/products").json()[0]["id"]

    resp = client.post(f"/products/{pid}/listing/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0
    assert any("Nome da peça" in e for e in data["errors"])


def test_validate_listing_complete(client, db):
    """Produto completo com imagem deve passar validacao."""
    pid = _create_enriched_product(client)

    # Gera listing com categoria mockada
    with patch("app.routers.listings.predict_category") as mock_cat:
        mock_cat.return_value = {"category_id": "MLB12345", "category_name": "Freios"}
        client.post(f"/products/{pid}/listing/generate")

    # Adiciona imagem diretamente no banco
    from app.models import Image, ImageType, Product

    product = db.query(Product).filter(Product.id == pid).first()
    db.add(Image(
        product_id=pid,
        image_type=ImageType.original,
        sort_order=1,
        filename="test.jpg",
        storage_path="/tmp/test.jpg",
        mime_type="image/jpeg",
    ))
    db.commit()

    resp = client.post(f"/products/{pid}/listing/validate")
    data = resp.json()
    assert data["valid"] is True
    assert data["errors"] == []


def test_validate_listing_not_found(client):
    resp = client.post("/products/999/listing/validate")
    assert resp.status_code == 404


def test_publish_listing_not_validated(client):
    pid = _create_enriched_product(client)

    with patch("app.routers.listings.predict_category") as mock_cat:
        mock_cat.return_value = {"category_id": "MLB12345", "category_name": "Freios"}
        client.post(f"/products/{pid}/listing/generate")

    resp = client.post(f"/products/{pid}/listing/publish")
    assert resp.status_code == 400
    assert "validado" in resp.json()["detail"].lower()


def test_publish_listing_not_found(client):
    resp = client.post("/products/999/listing/publish")
    assert resp.status_code == 404


def test_listing_title_truncated_to_60(client):
    # Cria produto com nome longo
    content = b"LONGNAME-001"
    client.post("/batches/import", files={"file": ("oems.txt", BytesIO(content), "text/plain")})
    pid = client.get("/products").json()[0]["id"]

    client.patch(f"/products/{pid}", json={
        "part_name": "Jogo Completo de Pastilhas de Freio Dianteiro e Traseiro",
        "brand": "Honda Original",
        "category": "Freio",
    })

    with patch("app.routers.listings.predict_category") as mock_cat:
        mock_cat.return_value = {"category_id": "MLB12345", "category_name": "Freios"}
        resp = client.post(f"/products/{pid}/listing/generate")

    assert len(resp.json()["title"]) <= 60
