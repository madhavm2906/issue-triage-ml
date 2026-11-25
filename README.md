# GitHub Issue Triage

A local tool for suggesting `bug` or `feature-request` on GitHub issues. FastAPI imports public issues into PostgreSQL. A scikit-learn model suggests a label, and the React dashboard lets a maintainer approve it or choose the other label. The review record keeps the text the model saw, its suggestion, and the final decision.

## Local setup

The demo uses Python 3.12, Docker Compose, and Node 24. Run the commands from the repository root on Ubuntu or WSL.

On a fresh checkout, create `.env` with these local settings. Use your existing `.env` if the database is already set up.

```dotenv
POSTGRES_DB=issue_triage
POSTGRES_USER=issue_triage
POSTGRES_PASSWORD=local-demo-password
DATABASE_URL=postgresql+psycopg://issue_triage:local-demo-password@127.0.0.1:5433/issue_triage
```

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-ml.txt
docker compose up -d
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave FastAPI running. Open a second terminal in the repository root.

## Prepare the model

If you already have both saved models and the original export, go to the dashboard step. For a new setup, run this in the second terminal.

```bash
for page in 1 2; do
    for label in bug feature-request; do
        curl --fail-with-body -sS -w '\n' -X POST \
            "http://127.0.0.1:8000/repositories/microsoft/vscode/import?state=all&page=$page&per_page=100&labels=$label" \
            || break 2
    done
done

.venv/bin/python export_dataset.py microsoft/vscode --output data/vscode_issues.jsonl
.venv/bin/python train_baseline.py data/vscode_issues.jsonl \
    --output-dir artifacts/issue_triage_baseline
.venv/bin/python compare_body.py
.venv/bin/python save_body_candidate.py
```

A new import pulls the latest issues, so it can produce different counts and scores. If a date split lacks one label, import earlier pages for both labels and export again before training. The recorded scores below came from the original 393 issue export.

## Try the review dashboard

From the repository root, print a few issue IDs and start the frontend.

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

lines = Path("data/vscode_issues.jsonl").read_text(encoding="utf-8").splitlines()
for line in lines[:5]:
    issue = json.loads(line)
    print(f'{issue["github_id"]} | #{issue["number"]} | {issue["title"]}')
PY

cd frontend
npm ci
npm run build && npm run dev
```

1. Open [http://localhost:5174](http://localhost:5174).
2. Copy the first number from a printed line into **Imported GitHub issue ID**. Click **Add to queue**.
3. Read the description and approve the suggestion or pick the other label.
4. Reload and add the same ID again. **Already reviewed** confirms the decision persisted. Use another ID to try a second review.

Review actions write to the local database. The same issue reuses its review record. A conflicting second decision returns HTTP 409.

## Model results

The original experiment used 275 training issues, 59 validation issues, and 59 test issues, split by creation time. Both models use TF-IDF and logistic regression.

| Model | Bug cutoff | Validation macro F1 | Validation bugs caught | Validation feature requests correct |
|---|---:|---:|---:|---:|
| Title only | 0.40 | 0.786 | 30/35 | 17/24 |
| Title and cleaned description | 0.45 | 0.864 | 27/35 | 24/24 |

The dashboard uses the title and cleaned description candidate. The fresh evaluation is pending. With FastAPI running, rerun the evaluator from the repository root.

```bash
.venv/bin/python evaluate_fresh.py
```

It waits for at least 20 newer examples of each label, saves that sample, and compares both models on the same issues.
