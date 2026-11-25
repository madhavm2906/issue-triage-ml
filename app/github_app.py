import argparse
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

from app.github import normalize_issue


@dataclass(frozen=True)
class Settings:
    repository: str
    app_id: str
    installation_id: str
    key_path: Path


def load_settings() -> Settings:
    names = (
        "GITHUB_TRIAGE_REPOSITORY", "GITHUB_APP_ID",
        "GITHUB_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY_PATH",
    )
    values = [os.environ.get(name, "").strip() for name in names]
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise RuntimeError("Set " + ", ".join(missing) + " in this terminal.")

    repository, app_id, installation_id, raw_path = values
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
        raise RuntimeError("Use owner/repo for GITHUB_TRIAGE_REPOSITORY.")
    if repository.split("/")[1] in {".", ".."}:
        raise RuntimeError("Repository name is invalid.")
    if not all(re.fullmatch(r"[1-9][0-9]*", item) for item in (app_id, installation_id)):
        raise RuntimeError("Use the numeric App ID and installation ID.")

    return Settings(repository.lower(), app_id, installation_id, Path(raw_path).expanduser())


def sign_app_token(settings: Settings) -> str:
    try:
        key = settings.key_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("Could not read the configured GitHub App key file.") from exc

    now = int(time.time())
    try:
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": settings.app_id},
            key,
            algorithm="RS256",
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise RuntimeError("Could not sign the GitHub App token. Check the PEM file.") from exc


def github_json(client, method, path, token, **kwargs):
    response = client.request(
        method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
    )
    if not response.is_success:
        raise RuntimeError(f"GitHub returned HTTP {response.status_code} for {method} {path}.")
    return response.json()


def verified_read_token(client, settings: Settings) -> str:
    name = settings.repository.split("/")[1]
    access = github_json(
        client, "POST", f"/app/installations/{settings.installation_id}/access_tokens",
        sign_app_token(settings),
        json={"repositories": [name], "permissions": {"issues": "read"}},
    )
    if access.get("permissions", {}).get("issues") != "read":
        raise RuntimeError("GitHub did not return read access to issues.")

    token = access["token"]
    installed = github_json(client, "GET", "/installation/repositories", token)
    repositories = installed["repositories"]
    if installed["total_count"] != 1 or len(repositories) != 1:
        raise RuntimeError("Expected a token scoped to exactly one repository.")
    repository = repositories[0]
    if repository["full_name"].lower() != settings.repository or not repository["private"]:
        raise RuntimeError("The token must match the configured private sandbox.")
    return token


def read_issue(client, settings: Settings, token: str, number: int) -> dict:
    item = github_json(client, "GET", f"/repos/{settings.repository}/issues/{number}", token)
    if "pull_request" in item:
        raise RuntimeError("That number belongs to a pull request. Choose an issue.")
    return normalize_issue(item)


def main():
    parser = argparse.ArgumentParser(description="Check a private GitHub App sandbox.")
    parser.add_argument("--import-issue", type=int, metavar="NUMBER")
    args = parser.parse_args()
    if args.import_issue is not None and args.import_issue < 1:
        parser.error("Issue number must be positive.")

    try:
        settings = load_settings()
        with httpx.Client(
            base_url="https://api.github.com",
            timeout=15,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "issue-triage-ml",
            },
        ) as client:
            token = verified_read_token(client, settings)
            print(f"Connected to {settings.repository} with read access.")
            if args.import_issue is not None:
                from app.storage import save_issues

                issue = read_issue(client, settings, token, args.import_issue)
                save_issues(settings.repository, [issue])
                print(f"Read and saved issue #{issue['number']} locally.")
    except (httpx.RequestError, RuntimeError, KeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
