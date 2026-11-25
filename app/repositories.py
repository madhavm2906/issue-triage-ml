from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from sqlalchemy import and_, case, select

from app.database import engine
from app.models import Issue, TriageReview

router = APIRouter(tags=["Saved issues"])
issues = Issue.__table__
reviews = TriageReview.__table__

Owner = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$")]
Repo = Annotated[str, Path(pattern=r"^[A-Za-z0-9_.-]+$")]
State = Literal["open", "closed", "all"]
IssueNumber = Annotated[int, Path(ge=1, le=2**31 - 1)]
Cursor = Annotated[int | None, Query(ge=1, le=2**31 - 1)]
Limit = Annotated[int, Query(ge=1, le=100)]

review_status = case(
    (reviews.c.id.is_(None), "unreviewed"),
    (reviews.c.final_label.is_(None), "pending"),
    (reviews.c.final_label == reviews.c.suggested_label, "approved"),
    else_="corrected",
).label("review_status")


@router.get("/repositories/{owner}/{repo}/issues")
def saved_issues(
    owner: Owner,
    repo: Repo,
    state: State = "all",
    before: Cursor = None,
    limit: Limit = 25,
) -> dict:
    repository = f"{owner}/{repo}".lower()
    current_review = and_(
        reviews.c.issue_id == issues.c.github_id,
        reviews.c.issue_version == issues.c.content_version,
    )
    statement = (
        select(issues.c.github_id, issues.c.number, issues.c.title, issues.c.state, review_status)
        .select_from(issues.outerjoin(reviews, current_review))
        .where(issues.c.repository == repository)
        .order_by(issues.c.number.desc())
        .limit(limit + 1)
    )
    if state != "all":
        statement = statement.where(issues.c.state == state)
    if before is not None:
        statement = statement.where(issues.c.number < before)

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()

    page = rows[:limit]
    return {
        "repository": repository,
        "issues": [{**row, "github_id": str(row["github_id"])} for row in page],
        "next_before": page[-1]["number"] if len(rows) > limit else None,
    }


@router.get("/repositories/{owner}/{repo}/issues/{number}")
def saved_issue_description(owner: Owner, repo: Repo, number: IssueNumber) -> dict[str, str]:
    repository = f"{owner}/{repo}".lower()
    statement = select(issues.c.body).where(
        issues.c.repository == repository, issues.c.number == number
    )
    with engine.connect() as connection:
        body = connection.execute(statement).scalar_one_or_none()
    if body is None:
        raise HTTPException(404, "Issue is not saved for this repository.")
    return {"body": body}
