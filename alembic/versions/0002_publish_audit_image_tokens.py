"""publish audit + image access tokens + listing idempotency

Revision ID: 0002_publish_audit_image_tokens
Revises: 0001_initial
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_publish_audit_image_tokens"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("listings") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(64), nullable=True))
        batch.add_column(sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_listings_idempotency_key", ["idempotency_key"])

    op.create_table(
        "publish_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("ml_item_id", sa.String(120), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_publish_events_listing_id", "publish_events", ["listing_id"])
    op.create_index("ix_publish_events_user_id", "publish_events", ["user_id"])
    op.create_index("ix_publish_events_idempotency_key", "publish_events", ["idempotency_key"])

    op.create_table(
        "image_access_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_image_access_tokens_token", "image_access_tokens", ["token"], unique=True)
    op.create_index("ix_image_access_tokens_user_id", "image_access_tokens", ["user_id"])
    op.create_index("ix_image_access_tokens_product_id", "image_access_tokens", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_image_access_tokens_product_id", table_name="image_access_tokens")
    op.drop_index("ix_image_access_tokens_user_id", table_name="image_access_tokens")
    op.drop_index("ix_image_access_tokens_token", table_name="image_access_tokens")
    op.drop_table("image_access_tokens")

    op.drop_index("ix_publish_events_idempotency_key", table_name="publish_events")
    op.drop_index("ix_publish_events_user_id", table_name="publish_events")
    op.drop_index("ix_publish_events_listing_id", table_name="publish_events")
    op.drop_table("publish_events")

    with op.batch_alter_table("listings") as batch:
        batch.drop_index("ix_listings_idempotency_key")
        batch.drop_column("publish_attempts")
        batch.drop_column("idempotency_key")
