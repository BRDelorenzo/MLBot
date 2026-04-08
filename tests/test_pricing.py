from io import BytesIO


def _create_product(client, oem="PRICE-001"):
    content = oem.encode()
    client.post("/batches/import", files={"file": ("oems.txt", BytesIO(content), "text/plain")})
    return client.get("/products").json()[0]["id"]


def test_calculate_pricing(client):
    pid = _create_product(client)
    resp = client.post(f"/products/{pid}/pricing/calculate", json={
        "cost": 50.0,
        "estimated_shipping": 15.0,
        "commission_percent": 0.16,
        "fixed_fee": 6.0,
        "margin_percent": 0.20,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["cost"] == 50.0
    assert data["suggested_price"] > 0
    # formula: (50 + 15 + 6) / (1 - 0.16 - 0.20) = 71 / 0.64 = 110.94
    assert data["suggested_price"] == 110.94
    assert data["final_price"] == 110.94


def test_pricing_not_found(client):
    resp = client.post("/products/999/pricing/calculate", json={"cost": 50.0})
    assert resp.status_code == 404


def test_pricing_zero_cost(client):
    pid = _create_product(client)
    resp = client.post(f"/products/{pid}/pricing/calculate", json={"cost": 0})
    assert resp.status_code == 422


def test_pricing_negative_cost(client):
    pid = _create_product(client)
    resp = client.post(f"/products/{pid}/pricing/calculate", json={"cost": -10})
    assert resp.status_code == 422


def test_pricing_commission_plus_margin_over_100(client):
    pid = _create_product(client)
    resp = client.post(f"/products/{pid}/pricing/calculate", json={
        "cost": 50.0,
        "commission_percent": 0.5,
        "margin_percent": 0.6,
    })
    assert resp.status_code == 400
    assert "100%" in resp.json()["detail"]


def test_pricing_update_existing(client):
    pid = _create_product(client)
    client.post(f"/products/{pid}/pricing/calculate", json={"cost": 50.0})

    resp = client.post(f"/products/{pid}/pricing/calculate", json={"cost": 100.0})
    assert resp.status_code == 200
    assert resp.json()["cost"] == 100.0
    assert resp.json()["suggested_price"] > 110.94  # maior que antes


def test_pricing_defaults(client):
    pid = _create_product(client)
    resp = client.post(f"/products/{pid}/pricing/calculate", json={"cost": 50.0})
    data = resp.json()
    assert data["estimated_shipping"] == 0
    assert data["commission_percent"] == 0.16
    assert data["fixed_fee"] == 0
    assert data["margin_percent"] == 0.20
