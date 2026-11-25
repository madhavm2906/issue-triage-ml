import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import urlopen

import joblib

from compare_body import DATA, RUN, measure, title_and_body

CANDIDATE = Path("artifacts/issue_triage_body_candidate")
SNAPSHOT = Path("data/vscode_fresh_with_body.jsonl")
MIN_PER_LABEL = 20
TITLE_CUTOFF = 0.40


def read_rows(payload):
    return [json.loads(line) for line in payload.splitlines() if line.strip()]


def created_at(row):
    return datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))


def title_key(title):
    return " ".join(title.casefold().split())


def collect_fresh(original, latest, labels):
    seen_ids = {row["github_id"] for row in original}
    seen_titles = {title_key(row["title"]) for row in original}
    fresh = []

    for page in range(1, 6):
        url = (
            "http://127.0.0.1:8000/github/microsoft/vscode/issues"
            f"?state=all&page={page}&per_page=100"
        )
        try:
            with urlopen(url, timeout=25) as response:
                batch = json.load(response)
        except URLError as exc:
            raise SystemExit(f"Could not fetch page {page} through FastAPI: {exc}") from exc

        reached_original = False
        for row in batch["issues"]:
            if created_at(row) <= latest:
                reached_original = True
                continue

            issue_id = row["github_id"]
            key = title_key(row["title"])
            targets = set(row["labels"]).intersection(labels)
            if issue_id in seen_ids or not key or key in seen_titles or len(targets) != 1:
                continue

            fresh.append({
                "github_id": issue_id,
                "created_at": row["created_at"],
                "title": row["title"].strip(),
                "body": row["body"],
                "label": targets.pop(),
            })
            seen_ids.add(issue_id)
            seen_titles.add(key)

        if reached_original or not batch["has_next_page"]:
            break

    return fresh


def freeze_snapshot(rows):
    with TemporaryDirectory(dir=SNAPSHOT.parent, prefix=".fresh-eval-") as temp:
        staged = Path(temp) / SNAPSHOT.name
        with staged.open("w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.link(staged, SNAPSHOT)


def print_score(name, expected, scores, labels, cutoff):
    macro_f1, bug_recall, feature_recall = measure(expected, scores, labels, cutoff)
    print(
        f"{name}: macro F1 {macro_f1:.3f} | bug recall {bug_recall:.1%}"
        f" | feature recall {feature_recall:.1%}"
    )


def main():
    report = json.loads((RUN / "metrics.json").read_text(encoding="utf-8"))
    metadata = json.loads((CANDIDATE / "metadata.json").read_text(encoding="utf-8"))
    payload = DATA.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != report["dataset_sha256"] or digest != metadata["dataset_sha256"]:
        raise SystemExit("Use the original JSONL export shared by both training runs.")

    original = read_rows(payload)
    latest = max(map(created_at, original))
    labels = report["labels"]
    frozen = SNAPSHOT.exists()
    fresh = (
        read_rows(SNAPSHOT.read_bytes())
        if frozen else collect_fresh(original, latest, labels)
    )

    counts = Counter(row["label"] for row in fresh)
    print(f"Original export ends at {latest.isoformat()}")
    print(f"Fresh candidates: bug={counts['bug']}, feature-request={counts['feature-request']}")
    if any(counts[label] < MIN_PER_LABEL for label in labels):
        print(f"Waiting for at least {MIN_PER_LABEL} examples of each label.")
        return

    if not frozen:
        freeze_snapshot(fresh)
    print(f"Evaluation snapshot: {SNAPSHOT}")

    expected = [row["label"] for row in fresh]
    print_score("Always predict bug", expected, [1.0] * len(fresh), labels, 0.50)

    cases = (
        ("Title only", RUN, TITLE_CUTOFF, [row["title"] for row in fresh]),
        ("Title + cleaned body", CANDIDATE, metadata["cutoff"], [
            title_and_body(row) for row in fresh
        ]),
    )
    for name, directory, cutoff, texts in cases:
        model = joblib.load(directory / "model.joblib")
        bug_column = list(model.classes_).index("bug")
        scores = model.predict_proba(texts)[:, bug_column]
        print_score(f"{name} ({cutoff:.2f})", expected, scores, labels, cutoff)


if __name__ == "__main__":
    main()
