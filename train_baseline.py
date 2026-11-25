import argparse
import hashlib
import json
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import joblib
from sklearn import __version__ as sklearn_version
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.pipeline import Pipeline

LABELS = ("bug", "feature-request")


@dataclass(frozen=True)
class Example:
    github_id: int
    created_at: datetime
    title: str
    label: str


def load_examples(payload: bytes) -> tuple[list[Example], Counter[str]]:
    examples = []
    skipped: Counter[str] = Counter()

    for line in payload.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        targets = set(row["labels"]).intersection(LABELS)
        if len(targets) != 1:
            skipped["both_labels" if targets else "neither_label"] += 1
            continue

        title = row["title"].strip()
        if not title:
            skipped["empty_title"] += 1
            continue

        examples.append(Example(
            github_id=row["github_id"],
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
            title=title,
            label=targets.pop(),
        ))

    examples.sort(key=lambda item: (item.created_at, item.github_id))
    unique = []
    seen_titles = set()
    for example in examples:
        title_key = " ".join(example.title.casefold().split())
        if title_key in seen_titles:
            skipped["duplicate_title"] += 1
            continue
        seen_titles.add(title_key)
        unique.append(example)

    return unique, skipped


def split_examples(examples: list[Example]) -> dict[str, list[Example]]:
    dates = [example.created_at for example in examples]
    train_end = bisect_left(dates, dates[int(len(dates) * 0.70)])
    validation_end = bisect_left(dates, dates[int(len(dates) * 0.85)])
    return {
        "train": examples[:train_end],
        "validation": examples[train_end:validation_end],
        "test": examples[validation_end:],
    }


def score(expected: list[str], predicted: list[str]) -> dict:
    metrics = classification_report(
        expected, predicted, labels=LABELS, output_dict=True, zero_division=0
    )
    return {
        "accuracy": metrics["accuracy"],
        "macro_f1": metrics["macro avg"]["f1-score"],
        "per_label": {label: metrics[label] for label in LABELS},
        "confusion_matrix": confusion_matrix(expected, predicted, labels=LABELS).tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the first issue triage baseline.")
    parser.add_argument("dataset", type=Path, help="Input JSONL file from export_dataset.py")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for this run")
    args = parser.parse_args()

    if args.output_dir.exists():
        parser.error(f"{args.output_dir} already exists. Choose a new output directory.")

    payload = args.dataset.read_bytes()
    examples, skipped = load_examples(payload)
    if len(examples) < 3:
        parser.error("Need more usable issues before creating time based splits.")

    splits = split_examples(examples)
    counts = {name: Counter(item.label for item in rows) for name, rows in splits.items()}
    print(f"Usable issues: {len(examples)}")
    print(f"Skipped: {dict(skipped)}")
    for name, rows in splits.items():
        print(f"{name}: {len(rows)} issues, {dict(counts[name])}")
    if any(set(counts[name]) != set(LABELS) for name in splits):
        parser.error("Each time based split needs both labels. Export more issues across a wider date range.")

    train = splits["train"]
    model = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        ("classifier", LogisticRegression(max_iter=1000, random_state=0)),
    ])
    model.fit([item.title for item in train], [item.label for item in train])
    majority = max(LABELS, key=lambda label: counts["train"][label])

    report = {
        "dataset_sha256": hashlib.sha256(payload).hexdigest(),
        "sklearn_version": sklearn_version,
        "labels": LABELS,
        "features": ["title"],
        "skipped": dict(skipped),
        "splits": {
            name: {
                "counts": dict(counts[name]),
                "first_created_at": rows[0].created_at.isoformat(),
                "last_created_at": rows[-1].created_at.isoformat(),
                "github_ids": [item.github_id for item in rows],
            }
            for name, rows in splits.items()
        },
    }
    for name in ("validation", "test"):
        rows = splits[name]
        expected = [item.label for item in rows]
        report[name] = {
            "majority": score(expected, [majority] * len(rows)),
            "tfidf_logistic": score(expected, model.predict([item.title for item in rows]).tolist()),
        }
        print(f"{name} macro F1")
        for model_name, metrics in report[name].items():
            print(f"  {model_name}: {metrics['macro_f1']:.3f}")

    args.output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output_dir.parent, prefix=".baseline-") as temp:
        staging = Path(temp) / "run"
        staging.mkdir()
        joblib.dump(model, staging / "model.joblib")
        (staging / "metrics.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(args.output_dir)
    print(f"Saved model and metrics to {args.output_dir}")


if __name__ == "__main__":
    main()
