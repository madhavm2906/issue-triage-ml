# Issue Triage ML

I built this to help maintainers sort incoming GitHub issues. The model reads the title and description and suggests either a bug or a feature request. A reviewer can accept the suggestion or change it. The worker applies the saved decision to GitHub in the configured private sandbox.

## Run it locally

```bash
bash scripts/triage.sh start
```

Open [the dashboard](http://127.0.0.1:8080/). Open your repository, click **Sync latest page**, then send an issue to review. After saving a decision, refresh **Repository Issues** to see the delivery status. The worker uses the GitHub labels `bug` and `enhancement`.

Use `bash scripts/triage.sh status` to check the services, `bash scripts/triage.sh logs` to see recent activity, and `bash scripts/triage.sh stop` when you are done.

## How it works

The React dashboard calls a FastAPI server. PostgreSQL keeps the issues, review history, and delivery queue. Editing an issue title or description creates a new version for review. Saving a decision and queueing its label happen in one database transaction. The worker checks the issue text on GitHub before applying the label and retries temporary delivery failures.

I trained a logistic regression classifier on TF IDF features from VS Code issues. I split the 393 labeled issues by creation date to evaluate on newer examples. At the default cutoff, adding the cleaned issue description improved validation macro F1 from 0.579 to 0.745. Tuning the cutoff on that same validation split raised it to 0.864. An evaluation on a separate batch of newer issues is still pending.

## Run the workflow test

```bash
bash scripts/test_workflow.sh
```

The test starts a fresh PostgreSQL database and simulates GitHub. It checks that saving a decision twice produces one label write and that the worker stays within its configured repository.

<details>
<summary>First time setup</summary>

Run these commands from the project folder with Docker Compose and Python 3.12 installed.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-ml.txt -r requirements-github.txt

if [[ ! -e .env ]]; then
    triage_db_password="$(python3.12 -c 'import secrets; print(secrets.token_hex(24))')"
    (
        umask 077
        cat > .env <<ENV
POSTGRES_DB=issue_triage
POSTGRES_USER=issue_triage
POSTGRES_PASSWORD=$triage_db_password
DATABASE_URL=postgresql+psycopg://issue_triage:$triage_db_password@127.0.0.1:5433/issue_triage
ENV
    )
fi

docker compose up -d --wait db
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

With the API running, open a second terminal in the project folder and collect labeled VS Code issues. The results can change as new issues are published.

```bash
(
    set -e
    for label in bug feature-request; do
        for page in 1 2; do
            curl -fsS -w '\n' -X POST \
                "http://127.0.0.1:8000/repositories/microsoft/vscode/import?page=$page&per_page=100&labels=$label"
        done
    done

    .venv/bin/python export_dataset.py microsoft/vscode --output data/vscode_issues.jsonl
    .venv/bin/python train_baseline.py data/vscode_issues.jsonl --output-dir artifacts/issue_triage_baseline
    .venv/bin/python compare_body.py
    .venv/bin/python save_body_candidate.py
)
```

Create a private GitHub App with Issues read and write access and turn off webhooks. Install it on one private sandbox repository and make sure that repository has the `bug` and `enhancement` labels. See [GitHub App registration](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) and [installation](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app).

Save the generated private key in your home configuration directory. Create `~/.config/issue-triage/compose.env` with your own values and the full path to that key. If you use `XDG_CONFIG_HOME`, put the file under its `issue-triage` folder.

```dotenv
GITHUB_APP_ID=YOUR_APP_ID
GITHUB_INSTALLATION_ID=YOUR_INSTALLATION_ID
GITHUB_TRIAGE_REPOSITORY=YOUR_ACCOUNT/YOUR_SANDBOX
GITHUB_APP_PRIVATE_KEY_PATH=/absolute/path/to/github-app.pem
```

Stop Uvicorn with Ctrl+C and run `bash scripts/triage.sh start`.

</details>
