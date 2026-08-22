"""Owner UI login sessions (dummy OTP in dev).

Revision ID: 8f2c4a91b0e3
Revises: 4c1d9a2e7b10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f2c4a91b0e3"
down_revision: str | Sequence[str] | None = "4c1d9a2e7b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner_sessions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_owner_session_token"),
    )
    op.create_index("ix_owner_sessions_store", "owner_sessions", ["store_id"])
    op.create_index("ix_owner_sessions_expiry", "owner_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_owner_sessions_expiry", table_name="owner_sessions")
    op.drop_index("ix_owner_sessions_store", table_name="owner_sessions")
    op.drop_table("owner_sessions")
