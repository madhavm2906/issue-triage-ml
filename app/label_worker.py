from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, func, insert, or_, select, update

from app.database import engine
from app.models import Issue, LabelUpdate, TriageReview

jobs = LabelUpdate.__table__
issues = Issue.__table__
reviews = TriageReview.__table__
MAX_ATTEMPTS = 5
LEASE_SECONDS = 60


class RetryableLabelError(Exception):
    """The sender can try this operation again."""

    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentLabelError(Exception):
    """The sender needs a maintainer to resolve the failure."""


def enqueue_label_update(connection, review, issue):
    connection.execute(
        insert(jobs).values(
            review_id=review["id"],
            repository=issue["repository"],
            issue_number=issue["number"],
            label=review["final_label"],
        )
    )


def lease_values(state):
    return {"state": state, "lease_token": None, "lease_until": None}


def claim(review_id=None):
    ready = or_(
        and_(jobs.c.state == "queued", jobs.c.available_at <= func.now()),
        and_(jobs.c.state == "sending", jobs.c.lease_until <= func.now()),
    )
    statement = select(jobs).where(ready)
    if review_id is not None:
        statement = statement.where(jobs.c.review_id == review_id)
    statement = statement.order_by(jobs.c.available_at, jobs.c.review_id)
    statement = statement.limit(1).with_for_update(skip_locked=True)

    with engine.begin() as connection:
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            return None

        target = update(jobs).where(jobs.c.review_id == row["review_id"])
        if row["attempts"] >= MAX_ATTEMPTS:
            connection.execute(target.values(
                **lease_values("failed"), last_error="Final worker lease expired."
            ))
            return None

        now = connection.execute(select(func.now())).scalar_one()
        leased = connection.execute(target.values(
            state="sending",
            attempts=row["attempts"] + 1,
            lease_token=uuid4().hex,
            lease_until=now + timedelta(seconds=LEASE_SECONDS),
        ).returning(*jobs.c)).mappings().one()
        return dict(leased)


def finish(job, state, *, error=None, delay_seconds=0):
    values = lease_values(state)
    values["last_error"] = error
    if state == "queued":
        values["available_at"] = func.now() + timedelta(seconds=delay_seconds)
    if state == "applied":
        values["applied_at"] = func.now()

    statement = update(jobs).where(
        jobs.c.review_id == job["review_id"],
        jobs.c.state == "sending",
        jobs.c.lease_token == job["lease_token"],
    ).values(**values)
    with engine.begin() as connection:
        updated = connection.execute(statement).rowcount
    return state if updated else "lease_lost"


def is_current(job):
    statement = (
        select(issues.c.github_id)
        .select_from(reviews.join(issues, reviews.c.issue_id == issues.c.github_id))
        .where(
            reviews.c.id == job["review_id"],
            reviews.c.issue_version == issues.c.content_version,
            issues.c.repository == job["repository"],
            issues.c.number == job["issue_number"],
        )
    )
    with engine.connect() as connection:
        return connection.execute(statement).scalar_one_or_none() is not None


def run_once(send: Callable[[dict], None], *, review_id=None):
    job = claim(review_id)
    if job is None:
        return None
    if not is_current(job):
        return finish(job, "superseded", error="The reviewed issue version changed.")

    try:
        send(job)
    except RetryableLabelError as exc:
        if job["attempts"] < MAX_ATTEMPTS:
            delay = max(5 * 2 ** (job["attempts"] - 1), exc.retry_after)
            return finish(job, "queued", error=str(exc), delay_seconds=delay)
        return finish(job, "failed", error=str(exc))
    except PermanentLabelError as exc:
        return finish(job, "failed", error=str(exc))

    return finish(job, "applied")
