"""initial — baseline vazio, schema criado via create_all em bancos pré-Alembic.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-14

Este revision serve apenas como baseline. Para bancos novos, o bootstrap cria
as tabelas via Base.metadata.create_all e executa `alembic stamp head` para
marcar este revision como aplicado. Mudanças futuras de schema devem ser
geradas com `alembic revision --autogenerate -m "descrição"`.
"""
from typing import Sequence, Union


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
