from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, insert, select, update

from app.database import engine
from app.label_worker import enqueue_label_update
from app.models import Issue, TriageReview
from app.prediction import IssueText, predict_issue

router = APIRouter(tags=["Reviews"])
issues = Issue.__table__
reviews = TriageReview.__table__
MAX_ID = 2**63 - 1
Label = Literal["bug", "feature-request"]
ReviewID = Annotated[int, Path(gt=0, le=MAX_ID)]

current_review = and_(
    reviews.c.issue_id == issues.c.github_id,
    reviews.c.issue_version == issues.c.content_version,
)


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
    with engine.begin() as connection:
        issue_query = select(issues).where(issues.c.github_id == request.issue_id)
        issue = connection.execute(issue_query.with_for_update()).mappings().one_or_none()
        if issue is None:
            raise HTTPException(404, "Import the issue before adding it to the review queue.")

        version = issue["content_version"]
        existing = connection.execute(
            select(reviews).where(
                reviews.c.issue_id == request.issue_id,
                reviews.c.issue_version == version,
            )
        ).mappings().one_or_none()
        if existing is not None:
            return review_data(existing)

        if not issue["title"].strip():
            raise HTTPException(422, "The imported issue has an empty title.")

        issue_text = IssueText(title=issue["title"], body=issue["body"])
        prediction = predict_issue(issue_text)
        row = connection.execute(
            insert(reviews).values(
                issue_id=request.issue_id,
                issue_version=version,
                title=issue_text.title,
                body=issue_text.body,
                suggested_label=prediction.suggested_label,
                bug_score=prediction.bug_score,
                bug_cutoff=prediction.bug_cutoff,
            ).returning(*reviews.c)
        ).mappings().one()
    return review_data(row)


@router.get("/reviews")
def list_pending_reviews(limit: Annotated[int, Query(ge=1, le=100)] = 50) -> list[dict]:
    statement = (
        select(reviews, issues.c.repository, issues.c.number)
        .join(issues, current_review)
        .where(reviews.c.final_label.is_(None))
        .order_by(reviews.c.id)
        .limit(limit)
    )
    with engine.connect() as connection:
        rows = connection.execute(statement).mappings()
        return [review_data(row) for row in rows]


@router.get("/reviews/{review_id}")
def get_review(review_id: ReviewID) -> dict:
    is_current = (reviews.c.issue_version == issues.c.content_version).label("is_current")
    statement = select(reviews, is_current).join(issues).where(reviews.c.id == review_id)
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Review not found.")
    return review_data(row)


@router.patch("/reviews/{review_id}")
def decide_review(review_id: ReviewID, decision: ReviewDecision) -> dict:
    review_query = select(reviews).where(reviews.c.id == review_id)
    with engine.begin() as connection:
        row = connection.execute(review_query).mappings().one_or_none()
        if row is None:
            raise HTTPException(404, "Review not found.")

        issue_query = select(issues).where(issues.c.github_id == row["issue_id"])
        issue = connection.execute(issue_query.with_for_update()).mappings().one()

        row = connection.execute(review_query).mappings().one()
        if row["final_label"] is not None:
            if row["final_label"] != decision.final_label:
                raise HTTPException(409, "This review already has a different decision.")
            return review_data(row)

        if row["issue_version"] != issue["content_version"]:
            raise HTTPException(409, "The issue changed. Send it to review again.")

        row = connection.execute(
            update(reviews).where(reviews.c.id == review_id)
            .values(final_label=decision.final_label, decided_at=func.now())
            .returning(*reviews.c)
        ).mappings().one()
        enqueue_label_update(connection, row, issue)
    return review_data(row)
