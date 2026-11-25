"""Add triage reviews."""

import sqlalchemy as sa
from alembic import op

revision = "2f4a0a5e3b71"
down_revision = "156a2840d921"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "triage_reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("issue_id", sa.BigInteger(), sa.ForeignKey("issues.github_id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("suggested_label", sa.String(16), nullable=False),
        sa.Column("bug_score", sa.Float(), nullable=False),
        sa.Column("bug_cutoff", sa.Float(), nullable=False),
        sa.Column("final_label", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("issue_id", name="uq_triage_reviews_issue_id"),
        sa.CheckConstraint(
            "suggested_label IN ('bug', 'feature-request')",
            name="ck_triage_reviews_suggested_label",
        ),
        sa.CheckConstraint(
            "final_label IN ('bug', 'feature-request')",
            name="ck_triage_reviews_final_label",
        ),
        sa.CheckConstraint(
            "bug_score BETWEEN 0 AND 1 AND bug_cutoff BETWEEN 0 AND 1",
            name="ck_triage_reviews_score_range",
        ),
        sa.CheckConstraint(
            "(final_label IS NULL) = (decided_at IS NULL)",
            name="ck_triage_reviews_decision",
        ),
    )


def downgrade():
    op.drop_table("triage_reviews")
