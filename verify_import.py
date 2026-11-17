from datetime import timedelta

from sqlalchemy import func, select

from app.database import engine
from app.models import Issue
from app.storage import ImportedIssue, save_issues

repository = "microsoft/vscode"
table = Issue.__table__

with engine.connect() as connection:
    stored = connection.execute(
        select(table).where(table.c.repository == repository)
    ).mappings().all()

assert stored, "No stored issues found."

items = [
    {field: row[field] for field in ImportedIssue.model_fields}
    for row in stored
]

save_issues(repository, items)
save_issues(repository, items)

with engine.connect() as connection:
    count = connection.execute(
        select(func.count())
        .select_from(table)
        .where(table.c.repository == repository)
    ).scalar_one()

assert count == len(items), "Repeated imports changed the record count."
print(f"Repeated import: PASS ({count} unique stored issues)")

older = dict(items[0])
older["updated_at"] -= timedelta(seconds=1)

result = save_issues(repository, [older])
assert result == {"written": 0, "skipped_older": 1}, result

with engine.connect() as connection:
    updated_at = connection.execute(
        select(table.c.updated_at)
        .where(table.c.github_id == older["github_id"])
    ).scalar_one()

assert updated_at == items[0]["updated_at"]
print("Older update: PASS (newer database version preserved)")

engine.dispose()
