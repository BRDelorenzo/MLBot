"""Prova de C5: dois tenants com o mesmo OEM não sobrescrevem arquivos."""

from pathlib import Path

from app.config import settings
from app.routers.products import _ensure_upload_dir


def test_upload_dir_isolated_per_user(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))

    dir_a = _ensure_upload_dir(user_id=1, product_oem="12345-ABC")
    dir_b = _ensure_upload_dir(user_id=2, product_oem="12345-ABC")

    assert dir_a != dir_b
    assert str(dir_a).endswith(str(Path("1") / "12345-ABC"))
    assert str(dir_b).endswith(str(Path("2") / "12345-ABC"))

    # Gravação cross-tenant não se toca
    (dir_a / "foto.jpg").write_bytes(b"A")
    (dir_b / "foto.jpg").write_bytes(b"B")
    assert (dir_a / "foto.jpg").read_bytes() == b"A"
    assert (dir_b / "foto.jpg").read_bytes() == b"B"


def test_upload_dir_blocks_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))

    safe = _ensure_upload_dir(user_id=1, product_oem="../evil")
    # `Path(oem).name` reduz ".." para "evil"
    assert safe.name == "evil"
    assert tmp_path.resolve() in safe.resolve().parents
