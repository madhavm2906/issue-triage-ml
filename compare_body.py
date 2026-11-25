import hashlib
import json
import re
from pathlib import Path

import joblib
from sklearn.base import clone
from sklearn.metrics import f1_score, recall_score

RUN = Path("artifacts/issue_triage_baseline")
DATA = Path("data/vscode_issues.jsonl")
THRESHOLDS = [percent / 100 for percent in range(20, 81, 5)]

TEMPLATE_LINE = re.compile(
    r"^(?:[-*+]\s+)?\[[ xX]\]\s+|"
    r"^(?:issue )?type:\s*(?:bug|feature[- ]request)\s*$|"
    r"^(?:vs code version|os version|user agent|commit|system info):",
    re.IGNORECASE,
)


def title_and_body(row):
    body = row.get("body") or ""
    body = re.sub(r"<!--.*?-->|\x60{3}.*?\x60{3}", " ", body, flags=re.DOTALL)
    body = re.sub(r"https?://\S+", " ", body)

    prose = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#") or TEMPLATE_LINE.match(line.replace("**", "")):
            continue
        prose.append(line)

    words = " ".join(prose).split()[:400]
    return row["title"].strip() + "\n" + " ".join(words)


def measure(expected, probabilities, labels, cutoff):
    predicted = ["bug" if p >= cutoff else "feature-request" for p in probabilities]
    macro_f1 = f1_score(expected, predicted, labels=labels, average="macro", zero_division=0)
    bug_recall, feature_recall = recall_score(
        expected, predicted, labels=labels, average=None, zero_division=0
    )
    return macro_f1, bug_recall, feature_recall


def main():
    report = json.loads((RUN / "metrics.json").read_text(encoding="utf-8"))
    payload = DATA.read_bytes()
    if hashlib.sha256(payload).hexdigest() != report["dataset_sha256"]:
        raise SystemExit("Use the original dataset export from the baseline run.")

    issues = {}
    for line in payload.splitlines():
        if line.strip():
            row = json.loads(line)
            issues[row["github_id"]] = row

    labels = report["labels"]
    train = [issues[i] for i in report["splits"]["train"]["github_ids"]]
    validation = [issues[i] for i in report["splits"]["validation"]["github_ids"]]
    train_labels = [next(label for label in labels if label in row["labels"]) for row in train]
    expected = [next(label for label in labels if label in row["labels"]) for row in validation]

    baseline = joblib.load(RUN / "model.joblib")
    candidate = clone(baseline)
    candidate.fit([title_and_body(row) for row in train], train_labels)

    print(f"Training issues: {len(train)} | Validation issues: {len(validation)}")
    for name, model, texts in (
        ("Title only", baseline, [row["title"].strip() for row in validation]),
        ("Title + cleaned body", candidate, [title_and_body(row) for row in validation]),
    ):
        bug_column = list(model.classes_).index("bug")
        probabilities = model.predict_proba(texts)[:, bug_column]
        scores = {cutoff: measure(expected, probabilities, labels, cutoff) for cutoff in THRESHOLDS}
        best = max(scores, key=lambda cutoff: (scores[cutoff][0], -abs(cutoff - 0.50)))
        for setting, cutoff in (("default", 0.50), ("best on validation", best)):
            macro_f1, bug_recall, feature_recall = scores[cutoff]
            print(
                f"{name} ({setting}, {cutoff:.2f}): macro F1 {macro_f1:.3f}, "
                f"bug recall {bug_recall:.1%}, feature recall {feature_recall:.1%}"
            )


if __name__ == "__main__":
    main()
