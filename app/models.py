from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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

    # Creation and update times supplied by GitHub.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    # Time this record was fetched into our system.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
