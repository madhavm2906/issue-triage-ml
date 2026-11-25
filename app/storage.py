from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, PositiveInt
from sqlalchemy import case, or_
from sqlalchemy.dialects.postgresql import insert

from app.database import engine
from app.models import Issue


class ImportedIssue(BaseModel):
    github_id: PositiveInt
    number: PositiveInt
    title: str
    body: str
    state: Literal["open", "closed"]
    labels: list[str]
    url: str
    created_at: AwareDatetime
    updated_at: AwareDatetime


def save_issues(repository: str, items: list[dict]) -> dict[str, int]:
    fetched_at = datetime.now(timezone.utc)
    by_id = {}

    for item in items:
        row = ImportedIssue.model_validate(item).model_dump()
        row.update(repository=repository.lower(), fetched_at=fetched_at)

        previous = by_id.get(row["github_id"])
        if previous is None or row["updated_at"] >= previous["updated_at"]:
            by_id[row["github_id"]] = row

    if not by_id:
        return {"written": 0, "skipped_older": 0}

    rows = [by_id[key] for key in sorted(by_id)]
    table = Issue.__table__
    statement = insert(table).values(rows)
    incoming = statement.excluded
    text_changed = or_(
        table.c.title.is_distinct_from(incoming.title),
        table.c.body.is_distinct_from(incoming.body),
    )
    updates = {
        column.name: incoming[column.name]
        for column in table.columns
        if column.name not in {"github_id", "content_version"}
    }
    updates["content_version"] = case(
        (text_changed, table.c.content_version + 1),
        else_=table.c.content_version,
    )

    statement = statement.on_conflict_do_update(
        index_elements=[table.c.github_id],
        set_=updates,
        where=incoming.updated_at >= table.c.updated_at,
    ).returning(table.c.github_id)

    with engine.begin() as connection:
        written = len(connection.execute(statement).scalars().all())

    return {
        "written": written,
        "skipped_older": len(rows) - written,
    }
