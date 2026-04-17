"""One-shot: move uploads/{oem}/* para uploads/{user_id}/{oem}/* (C5).

Lê `product.user_id` e `product.oem` do DB, move cada arquivo original/processed
do produto para o novo layout e atualiza `image.storage_path`. Seguro para
rodar múltiplas vezes (idempotente).

Uso:
    python -m scripts.migrate_uploads_multitenant           # dry-run
    python -m scripts.migrate_uploads_multitenant --apply   # executa
"""

import shutil
import sys
from pathlib import Path

from app.config import settings
from app.database import SessionLocal
from app.models import Image, Product


def main(apply: bool = False) -> int:
    root = Path(settings.upload_dir).resolve()
    db = SessionLocal()
    moved = 0
    skipped = 0
    missing = 0
    try:
        images = db.query(Image).join(Product, Image.product_id == Product.id).all()
        for img in images:
            product = db.query(Product).filter(Product.id == img.product_id).first()
            if not product:
                continue

            current = Path(img.storage_path)
            target_dir = root / str(product.user_id) / Path(product.oem).name
            target = target_dir / Path(img.filename or current.name).name

            try:
                already_correct = current.resolve().is_relative_to(target_dir.resolve())
            except (OSError, ValueError):
                already_correct = False

            if already_correct:
                skipped += 1
                continue

            if not current.exists():
                missing += 1
                continue

            print(f"mv {current} -> {target}")
            moved += 1
            if apply:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current), str(target))
                img.storage_path = str(target)

        if apply:
            db.commit()
    finally:
        db.close()

    print(f"\nResumo: moved={moved} skipped={skipped} missing={missing} apply={apply}")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
