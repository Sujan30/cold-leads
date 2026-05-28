"""add twenty_person_id and twenty_opportunity_id to leads

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("twenty_person_id", sa.String(100), nullable=True))
    op.add_column("leads", sa.Column("twenty_opportunity_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "twenty_opportunity_id")
    op.drop_column("leads", "twenty_person_id")
