from typing import Annotated

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
    data = await list_repository_issues(
        owner, repo, state, page, per_page, labels=labels
    )
    repository = data["repository"].lower()

    try:
        result = await run_in_threadpool(
            save_issues, repository, data["issues"]
        )
    except ValidationError as exc:
        raise HTTPException(502, "GitHub issue data failed validation.") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Could not save issues to the database.") from exc

    return {
        "repository": repository,
        "page": page,
        "fetched": len(data["issues"]),
        **result,
        "has_next_page": data["has_next_page"],
    }
