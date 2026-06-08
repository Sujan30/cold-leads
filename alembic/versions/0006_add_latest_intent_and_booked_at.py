"""add latest_intent and booked_at to leads

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("latest_intent", sa.String(100), nullable=True))
    op.add_column("leads", sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "booked_at")
    op.drop_column("leads", "latest_intent")
