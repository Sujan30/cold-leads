"""Add reply_due_at and reply_first_pending_at to leads

Revision ID: 0004
Revises: 0003
"""
from typing import Union
import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("reply_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("reply_first_pending_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_leads_reply_due_at", "leads", ["reply_due_at"])


def downgrade() -> None:
    op.drop_index("ix_leads_reply_due_at", table_name="leads")
    op.drop_column("leads", "reply_first_pending_at")
    op.drop_column("leads", "reply_due_at")
