from os import getenv
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.github import list_repository_issues
from app.prediction import router as prediction_router
from app.repositories import Owner, Repo, State
from app.repositories import router as repository_router
from app.reviews import router as review_router
from app.storage import save_issues

app = FastAPI(
    title="Issue Triage ML",
    description="GitHub issue triage, model evaluation, and review API.",
    version="0.1.0",
)
app.include_router(prediction_router)
app.include_router(repository_router)
app.include_router(review_router)

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Labels = Annotated[
    str | None, Query(min_length=1, description="Comma-separated GitHub label names.")
]


def private_read_token(repository: str) -> str:
    try:
        from jwt.exceptions import PyJWTError

        from app.github_app import github_client, load_settings, verified_token
    except ModuleNotFoundError as exc:
        if exc.name != "jwt":
            raise
        raise HTTPException(
            503, "Install requirements-github.txt to sync the private repository."
        ) from exc

    try:
        settings = load_settings()
        if settings.repository.lower() != repository:
            raise RuntimeError("GitHub App repository does not match the request.")
        with github_client() as client:
            return verified_token(client, settings, permission="read")
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "GitHub App authentication timed out.") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 429):
            raise HTTPException(
                exc.response.status_code,
                "GitHub denied the App request or applied a rate limit.",
            ) from exc
        raise HTTPException(
            502, "GitHub could not authorize the private repository sync."
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not connect to GitHub.") from exc
    except (RuntimeError, OSError, ValueError, PyJWTError) as exc:
        raise HTTPException(
            503, "Check the GitHub App configuration and repository access."
        ) from exc


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "issue-triage-ml"}


@app.get("/github/{owner}/{repo}/issues", tags=["GitHub"])
async def repository_issues(
    owner: Owner,
    repo: Repo,
    state: State = "all",
    page: Page = 1,
    per_page: PageSize = 20,
    labels: Labels = None,
) -> dict:
    return await list_repository_issues(
        owner, repo, state, page, per_page, labels=labels
    )


@app.post("/repositories/{owner}/{repo}/import", tags=["Imports"])
async def import_issues(
    owner: Owner,
    repo: Repo,
    state: State = "all",
    page: Page = 1,
    per_page: PageSize = 20,
    labels: Labels = None,
) -> dict:
    repository = f"{owner}/{repo}".lower()
    configured_repository = getenv("GITHUB_TRIAGE_REPOSITORY", "").strip().lower()
    token = None
    if repository == configured_repository:
        token = await run_in_threadpool(private_read_token, repository)

    data = await list_repository_issues(
        owner, repo, state, page, per_page, labels=labels, token=token
    )

    try:
        result = await run_in_threadpool(
            save_issues, repository, data["issues"]
        )
    except ValidationError as exc:
        raise HTTPException(
            502, "GitHub issue data failed validation."
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            503, "Could not save issues to the database."
        ) from exc

    return {
        "repository": repository,
        "page": page,
        "fetched": len(data["issues"]),
        **result,
        "has_next_page": data["has_next_page"],
    }
