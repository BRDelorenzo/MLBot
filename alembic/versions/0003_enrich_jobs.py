"""enrich jobs — fila de bulk-enrich com progresso

Revision ID: 0003_enrich_jobs
Revises: 0002_publish_audit_image_tokens
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_enrich_jobs"
down_revision: Union[str, None] = "0002_publish_audit_image_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "enrich_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("status", sa.Enum("queued", "running", "completed", "failed", name="enrichjobstatus"), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_enrich_jobs_user_id", "enrich_jobs", ["user_id"])
    op.create_index("ix_enrich_jobs_batch_id", "enrich_jobs", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_enrich_jobs_batch_id", table_name="enrich_jobs")
    op.drop_index("ix_enrich_jobs_user_id", table_name="enrich_jobs")
    op.drop_table("enrich_jobs")
