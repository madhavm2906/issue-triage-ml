"""Queue reviewed label updates."""

import sqlalchemy as sa
from alembic import op

revision = "a392e8c6b54f"
down_revision = "6b18cf4a7d20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "label_updates",
        sa.Column("review_id", sa.BigInteger(), sa.ForeignKey("triage_reviews.id"),
                  primary_key=True, autoincrement=False),
        sa.Column("repository", sa.String(256), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.CheckConstraint(
            "state IN ('queued', 'sending', 'applied', 'failed', 'superseded')",
            name="ck_label_updates_state",
        ),
    )
    op.create_index("ix_label_updates_ready", "label_updates", ["state", "available_at", "review_id"])


def downgrade():
    op.drop_table("label_updates")
