"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("property_interest", sa.String(500), nullable=True),
        sa.Column(
            "temperature",
            sa.Enum("hot_inbound", "aged", name="leadtemperature"),
            nullable=False,
            server_default="aged",
        ),
        sa.Column(
            "state",
            sa.Enum(
                "new",
                "contacted",
                "engaged",
                "qualifying",
                "booked",
                "handed_off",
                "no_reply",
                "dormant",
                name="leadstate",
            ),
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "channel",
            sa.Enum("text", "email", name="leadchannel"),
            nullable=False,
            server_default="email",
        ),
        sa.Column("consent_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_leads_phone", "leads", ["phone"])
    op.create_index("ix_leads_state", "leads", ["state"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("inbound", "outbound", name="messagedirection"),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.Enum("text", "email", name="messagechannel"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("ai_model", sa.String(100), nullable=True),
        sa.Column("intent", sa.String(100), nullable=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_messages_lead_id", "messages", ["lead_id"])

    op.create_table(
        "follow_ups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("touch_number", sa.Integer(), nullable=False),
        sa.Column("sent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_follow_ups_lead_id", "follow_ups", ["lead_id"])
    op.create_index("ix_follow_ups_scheduled_for", "follow_ups", ["scheduled_for"])


def downgrade() -> None:
    op.drop_table("follow_ups")
    op.drop_table("messages")
    op.drop_table("leads")
    op.execute("DROP TYPE IF EXISTS leadtemperature")
    op.execute("DROP TYPE IF EXISTS leadstate")
    op.execute("DROP TYPE IF EXISTS leadchannel")
    op.execute("DROP TYPE IF EXISTS messagedirection")
    op.execute("DROP TYPE IF EXISTS messagechannel")
