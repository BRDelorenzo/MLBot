from io import BytesIO


def _import_oem(client, oem="TEST-OEM-001"):
    """Helper: importa um OEM e retorna o product_id."""
    content = oem.encode()
    client.post("/batches/import", files={"file": ("oems.txt", BytesIO(content), "text/plain")})
    products = client.get("/products").json()
    return products[0]["id"]


def test_list_products_empty(client):
    resp = client.get("/products")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_products_after_import(client):
    _import_oem(client, "OEM-A")
    resp = client.get("/products")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["oem"] == "OEM-A"


def test_get_product_not_found(client):
    resp = client.get("/products/999")
    assert resp.status_code == 404


def test_get_product_by_id(client):
    pid = _import_oem(client, "OEM-GET")
    resp = client.get(f"/products/{pid}")
    assert resp.status_code == 200
    assert resp.json()["oem"] == "OEM-GET"


def test_update_product(client):
    pid = _import_oem(client)
    resp = client.patch(f"/products/{pid}", json={"part_name": "Disco de Freio", "brand": "Honda"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["part_name"] == "Disco de Freio"
    assert data["brand"] == "Honda"


def test_update_product_rejects_empty_string(client):
    pid = _import_oem(client)
    resp = client.patch(f"/products/{pid}", json={"part_name": ""})
    assert resp.status_code == 422


def test_update_product_not_found(client):
    resp = client.patch("/products/999", json={"part_name": "X"})
    assert resp.status_code == 404


def test_update_product_partial(client):
    pid = _import_oem(client)
    client.patch(f"/products/{pid}", json={"part_name": "Disco", "brand": "Honda"})
    # Atualiza apenas brand, part_name deve manter
    resp = client.patch(f"/products/{pid}", json={"brand": "Yamaha"})
    data = resp.json()
    assert data["part_name"] == "Disco"
    assert data["brand"] == "Yamaha"


def test_mock_enrich(client):
    pid = _import_oem(client)
    resp = client.post(f"/products/{pid}/mock-enrich")
    assert resp.status_code == 200
    data = resp.json()
    assert data["part_name"] is not None
    assert data["brand"] is not None
    assert data["category"] is not None
    assert data["confidence_level"] == 80
    assert len(data["compatibilities"]) >= 1
    assert len(data["attributes"]) >= 2


def test_mock_enrich_not_found(client):
    resp = client.post("/products/999/mock-enrich")
    assert resp.status_code == 404


def test_mock_enrich_idempotent(client):
    pid = _import_oem(client)
    client.post(f"/products/{pid}/mock-enrich")
    resp = client.post(f"/products/{pid}/mock-enrich")
    data = resp.json()
    # Nao deve duplicar compatibilidades/atributos
    assert len(data["compatibilities"]) == 1
    assert len(data["attributes"]) == 2


def test_filter_products_by_status(client):
    _import_oem(client, "OEM-FILTER")
    resp = client.get("/products?status=normalized")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.get("/products?status=published")
    assert resp.status_code == 200
    assert len(resp.json()) == 0
