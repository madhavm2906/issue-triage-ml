import argparse
import json
from collections import Counter
from itertools import chain
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy import func, select

from app.database import engine
from app.models import Issue


def write_dataset(rows, output: Path) -> tuple[int, Counter[str]]:
    rows = iter(rows)
    first = next(rows, None)
    label_counts: Counter[str] = Counter()

    if first is None:
        return 0, label_counts

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_file = NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=output.parent,
        delete=False,
    )
    temp_path = Path(temp_file.name)

    try:
        with temp_file:
            for count, row in enumerate(chain((first,), rows), start=1):
                record = dict(row)
                for field in ("created_at", "updated_at", "fetched_at"):
                    record[field] = record[field].isoformat()
                temp_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                label_counts.update(set(record["labels"]))

        temp_path.replace(output)
    finally:
        temp_path.unlink(missing_ok=True)

    return count, label_counts


def export_dataset(repository: str, output: Path) -> tuple[int, Counter[str]]:
    statement = (
        select(
            Issue.github_id,
            Issue.repository,
            Issue.number,
            Issue.title,
            Issue.body,
            Issue.labels,
            Issue.created_at,
            Issue.updated_at,
            Issue.fetched_at,
        )
        .where(
            Issue.repository == repository,
            func.jsonb_array_length(Issue.labels) > 0,
        )
        .order_by(Issue.created_at, Issue.github_id)
    )

    with engine.connect() as connection:
        result = connection.execution_options(yield_per=1000).execute(statement)
        return write_dataset(result.mappings(), output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export labeled GitHub issues.")
    parser.add_argument("repository", help="GitHub repository in owner/name form")
    parser.add_argument("--output", required=True, type=Path, help="JSONL output file")
    args = parser.parse_args()

    repository = args.repository.strip().lower()
    count, label_counts = export_dataset(repository, args.output)

    if count == 0:
        raise SystemExit(f"No labeled issues found for {repository}. Import more issues first.")

    print(f"Exported {count} labeled issues to {args.output}")
    print("Label counts (one issue can have multiple labels)")
    for label, count in sorted(label_counts.items(), key=lambda entry: (-entry[1], entry[0])):
        print(f"  {label}: {count}")


if __name__ == "__main__":
    main()
