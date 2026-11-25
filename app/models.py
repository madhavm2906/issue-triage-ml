from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Issue(Base):
    __tablename__ = "issues"

    __table_args__ = (
        UniqueConstraint(
            "repository", "number",
            name="uq_issues_repository_number",
        ),
        CheckConstraint(
            "state IN ('open', 'closed')",
            name="ck_issues_state",
        ),
        CheckConstraint(
            "number > 0",
            name="ck_issues_positive_number",
        ),
        Index(
            "ix_issues_repository_updated_at",
            "repository", "updated_at",
        ),
    )

    github_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    repository: Mapped[str] = mapped_column(String(256))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16))
    labels: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    url: Mapped[str] = mapped_column(Text)
    content_version: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))

    # Creation and update times supplied by GitHub.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Time this record was fetched into our system.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class TriageReview(Base):
    __tablename__ = "triage_reviews"

    __table_args__ = (
        UniqueConstraint("issue_id", "issue_version", name="uq_triage_reviews_issue_version"),
        CheckConstraint(
            "suggested_label IN ('bug', 'feature-request')",
            name="ck_triage_reviews_suggested_label",
        ),
        CheckConstraint(
            "final_label IN ('bug', 'feature-request')",
            name="ck_triage_reviews_final_label",
        ),
        CheckConstraint(
            "bug_score BETWEEN 0 AND 1 AND bug_cutoff BETWEEN 0 AND 1",
            name="ck_triage_reviews_score_range",
        ),
        CheckConstraint(
            "(final_label IS NULL) = (decided_at IS NULL)",
            name="ck_triage_reviews_decision",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    issue_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("issues.github_id"))
    issue_version: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    suggested_label: Mapped[str] = mapped_column(String(16))
    bug_score: Mapped[float] = mapped_column(Float)
    bug_cutoff: Mapped[float] = mapped_column(Float)
    final_label: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
