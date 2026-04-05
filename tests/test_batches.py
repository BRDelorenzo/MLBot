from io import BytesIO


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_import_batch_success(client):
    content = b"ABC123\nDEF456\nGHI789\n"
    resp = client.post(
        "/batches/import",
        files={"file": ("oems.txt", BytesIO(content), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 3
    assert data["total_valid"] == 3
    assert data["filename"] == "oems.txt"


def test_import_batch_deduplicates(client):
    content = b"ABC123\nabc123\nABC-123\nDEF456\n"
    resp = client.post(
        "/batches/import",
        files={"file": ("oems.txt", BytesIO(content), "text/plain")},
    )
    data = resp.json()
    # ABC123 e ABC-123 are different after normalization (hyphen kept)
    # abc123 -> ABC123 (duplicate)
    assert data["total_items"] == 3


def test_import_batch_rejects_non_txt(client):
    resp = client.post(
        "/batches/import",
        files={"file": ("oems.csv", BytesIO(b"data"), "text/csv")},
    )
    assert resp.status_code == 400


def test_list_batches_empty(client):
    resp = client.get("/batches")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_batch_items(client):
    content = b"PART001\nPART002\n"
    resp = client.post(
        "/batches/import",
        files={"file": ("parts.txt", BytesIO(content), "text/plain")},
    )
    batch_id = resp.json()["id"]

    resp = client.get(f"/batches/{batch_id}/items")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert items[0]["oem_normalized"] == "PART001"
