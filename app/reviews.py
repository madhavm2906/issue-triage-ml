from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database import engine
from app.models import Issue, TriageReview
from app.prediction import IssueText, predict_issue

router = APIRouter(tags=["Reviews"])
issues = Issue.__table__
reviews = TriageReview.__table__
MAX_ID = 2**63 - 1
Label = Literal["bug", "feature-request"]


class QueueRequest(BaseModel):
    issue_id: Annotated[int, Field(gt=0, le=MAX_ID)]


class ReviewDecision(BaseModel):
    final_label: Label


def review_data(row) -> dict:
    data = dict(row)
    if data["final_label"] is None:
        status = "pending"
    elif data["final_label"] == data["suggested_label"]:
        status = "approved"
    else:
        status = "corrected"
    return {**data, "status": status}


@router.post("/reviews")
def queue_issue(request: QueueRequest) -> dict:
    existing_query = select(reviews).where(reviews.c.issue_id == request.issue_id)

    with engine.connect() as connection:
        existing = connection.execute(existing_query).mappings().one_or_none()
        if existing is not None:
            return review_data(existing)

        issue = connection.execute(
            select(issues.c.title, issues.c.body)
            .where(issues.c.github_id == request.issue_id)
        ).mappings().one_or_none()

    if issue is None:
        raise HTTPException(404, "Import the issue before adding it to the review queue.")
    if not issue["title"].strip():
        raise HTTPException(422, "The imported issue has an empty title.")

    issue_text = IssueText(title=issue["title"], body=issue["body"])
    prediction = predict_issue(issue_text)
    statement = (
        insert(reviews)
        .values(
            issue_id=request.issue_id,
            title=issue_text.title,
            body=issue_text.body,
            suggested_label=prediction.suggested_label,
            bug_score=prediction.bug_score,
            bug_cutoff=prediction.bug_cutoff,
        )
        .on_conflict_do_nothing(index_elements=[reviews.c.issue_id])
    )

    with engine.begin() as connection:
        connection.execute(statement)
        row = connection.execute(existing_query).mappings().one()
    return review_data(row)


@router.get("/reviews")
def list_pending_reviews(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict]:
    statement = (
        select(reviews, issues.c.repository, issues.c.number)
        .join(issues, reviews.c.issue_id == issues.c.github_id)
        .where(reviews.c.final_label.is_(None))
        .order_by(reviews.c.id)
        .limit(limit)
    )

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings()
        return [review_data(row) for row in rows]


@router.patch("/reviews/{review_id}")
def decide_review(
    review_id: Annotated[int, Path(gt=0, le=MAX_ID)],
    decision: ReviewDecision,
) -> dict:
    statement = (
        update(reviews)
        .where(reviews.c.id == review_id, reviews.c.final_label.is_(None))
        .values(final_label=decision.final_label, decided_at=func.now())
        .returning(*reviews.c)
    )
    with engine.begin() as connection:
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            row = connection.execute(
                select(reviews).where(reviews.c.id == review_id)
            ).mappings().one_or_none()
            if row is None:
                raise HTTPException(404, "Review not found.")
            if row["final_label"] != decision.final_label:
                raise HTTPException(409, "This review already has a different decision.")

    return review_data(row)
