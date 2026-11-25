import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import joblib
from sklearn.base import clone

from compare_body import DATA, RUN, measure, title_and_body

OUTPUT = Path("artifacts/issue_triage_body_candidate")
CUTOFF = 0.45


def main():
    if OUTPUT.exists():
        raise SystemExit(f"Candidate already exists at {OUTPUT}")

    report = json.loads((RUN / "metrics.json").read_text(encoding="utf-8"))
    payload = DATA.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != report["dataset_sha256"]:
        raise SystemExit("Use the original dataset export from the baseline run.")

    issues = {}
    for line in payload.splitlines():
        if line.strip():
            row = json.loads(line)
            issues[row["github_id"]] = row

    labels = report["labels"]
    train_ids = report["splits"]["train"]["github_ids"]
    validation_ids = report["splits"]["validation"]["github_ids"]
    train = [issues[issue_id] for issue_id in train_ids]
    validation = [issues[issue_id] for issue_id in validation_ids]
    train_labels = [next(label for label in labels if label in row["labels"]) for row in train]
    expected = [next(label for label in labels if label in row["labels"]) for row in validation]

    candidate = clone(joblib.load(RUN / "model.joblib"))
    candidate.fit([title_and_body(row) for row in train], train_labels)

    bug_column = list(candidate.classes_).index("bug")
    probabilities = candidate.predict_proba(
        [title_and_body(row) for row in validation]
    )[:, bug_column]
    macro_f1, bug_recall, feature_recall = measure(
        expected, probabilities, labels, CUTOFF
    )

    metadata = {
        "dataset_sha256": digest,
        "train_issue_ids": train_ids,
        "validation_issue_ids": validation_ids,
        "preprocessing": "compare_body.title_and_body",
        "positive_label": "bug",
        "cutoff": CUTOFF,
        "validation": {
            "macro_f1": macro_f1,
            "bug_recall": bug_recall,
            "feature_request_recall": feature_recall,
        },
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=OUTPUT.parent, prefix=".body-candidate-") as temp:
        staging = Path(temp) / "run"
        staging.mkdir()
        joblib.dump(candidate, staging / "model.joblib")
        (staging / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(OUTPUT)

    print(f"Validation macro F1 at {CUTOFF:.2f}: {macro_f1:.3f}")
    print(f"Saved candidate to {OUTPUT}")


if __name__ == "__main__":
    main()
