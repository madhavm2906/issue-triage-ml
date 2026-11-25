"""Version issue text and its review snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "6b18cf4a7d20"
down_revision = "2f4a0a5e3b71"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "issues",
        sa.Column("content_version", sa.BigInteger(), nullable=False, server_default="1"),
    )
    op.add_column(
        "triage_reviews",
        sa.Column("issue_version", sa.BigInteger(), nullable=False, server_default="0"),
    )

    connection = op.get_bind()
    reviews = sa.table("triage_reviews", sa.column("id"), sa.column("issue_version"))
    saved = connection.execute(sa.text("""
        SELECT r.id, r.title, r.body, i.title AS issue_title, i.body AS issue_body
        FROM triage_reviews AS r JOIN issues AS i ON i.github_id = r.issue_id
    """)).mappings()
    for batch in saved.partitions(250):
        matches = [
            row["id"] for row in batch
            if row["title"] == row["issue_title"].strip() and row["body"] == row["issue_body"]
        ]
        if matches:
            connection.execute(
                reviews.update().where(reviews.c.id.in_(matches)).values(issue_version=1)
            )

    op.alter_column("triage_reviews", "issue_version", server_default=None)
    op.create_unique_constraint(
        "uq_triage_reviews_issue_version", "triage_reviews", ["issue_id", "issue_version"]
    )
    op.drop_constraint("uq_triage_reviews_issue_id", "triage_reviews", type_="unique")


def downgrade():
    # Restore the original constraint first so duplicate history stops the downgrade safely.
    op.create_unique_constraint("uq_triage_reviews_issue_id", "triage_reviews", ["issue_id"])
    op.drop_constraint("uq_triage_reviews_issue_version", "triage_reviews", type_="unique")
    op.drop_column("triage_reviews", "issue_version")
    op.drop_column("issues", "content_version")
