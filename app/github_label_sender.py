import argparse
import time

import httpx
from sqlalchemy import select

from app.database import engine
from app.github_app import github_client, github_json, load_settings, read_issue, verified_token
from app.label_worker import PermanentLabelError, RetryableLabelError, is_current, run_once
from app.models import LabelUpdate, TriageReview

LABELS = {"bug": "bug", "feature-request": "enhancement"}
jobs = LabelUpdate.__table__
reviews = TriageReview.__table__


def load_review(review_id, repository):
    statement = (
        select(jobs, reviews.c.issue_id, reviews.c.title, reviews.c.body, reviews.c.final_label)
        .join(reviews, reviews.c.id == jobs.c.review_id)
        .where(jobs.c.review_id == review_id, jobs.c.repository == repository)
    )
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().one_or_none()
    if row is None or row["final_label"] != row["label"] or row["label"] not in LABELS:
        raise RuntimeError("No matching review job for this sandbox.")
    return dict(row)


def check_issue(client, settings, token, snapshot):
    issue = read_issue(client, settings, token, snapshot["issue_number"])
    if (
        issue["github_id"] != snapshot["issue_id"]
        or issue["title"].strip() != snapshot["title"]
        or issue["body"] != snapshot["body"]
    ):
        raise PermanentLabelError("The GitHub issue changed. Import and review it again.")

    desired = LABELS[snapshot["label"]]
    existing = {label.casefold() for label in issue["labels"]}
    if existing.intersection(LABELS.values()) - {desired}:
        raise PermanentLabelError("GitHub already has a different triage label.")
    return desired, desired in existing


def delivery_error(response):
    status = response.status_code
    error = f"GitHub returned HTTP {status} during label delivery."
    headers = response.headers
    retry_after = headers.get("retry-after", "")
    reset = headers.get("x-ratelimit-reset", "")
    exhausted = headers.get("x-ratelimit-remaining") == "0"
    limited = status == 429 or (
        status == 403 and (retry_after or exhausted or "secondary rate limit" in response.text.lower())
    )
    if limited:
        delay = int(retry_after) if retry_after.isdecimal() else 60
        if exhausted and reset.isdecimal():
            delay = max(delay, int(int(reset) - time.time()) + 2)
        return RetryableLabelError(error, retry_after=delay)
    if status >= 500 or status == 408:
        return RetryableLabelError(error)
    return PermanentLabelError(error)


def deliver(client, settings, token, snapshot, job):
    if job["repository"] != settings.repository:
        raise PermanentLabelError("Unexpected job repository.")

    try:
        desired, present = check_issue(client, settings, token, snapshot)
        if present:
            return
        path = f"/repos/{settings.repository}/issues/{snapshot['issue_number']}/labels"
        result = github_json(client, "POST", path, token, json={"labels": [desired]})
        if not any(row["name"].casefold() == desired for row in result):
            raise PermanentLabelError("GitHub did not return the requested label.")
    except httpx.HTTPStatusError as exc:
        raise delivery_error(exc.response) from exc
    except httpx.RequestError as exc:
        raise RetryableLabelError("GitHub connection failed.") from exc
    except RuntimeError as exc:
        raise PermanentLabelError(str(exc)) from exc


def main():
    parser = argparse.ArgumentParser(description="Check or deliver one sandbox label update.")
    parser.add_argument("--review-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.review_id <= 2**63 - 1:
        parser.error("Invalid review ID.")

    try:
        settings = load_settings()
        snapshot = load_review(args.review_id, settings.repository)
        if snapshot["state"] == "applied":
            print(f"Review {args.review_id} is already applied.")
            return
        if not is_current(snapshot):
            raise RuntimeError("The local issue version changed. Review it again.")

        permission = "write" if args.apply else "read"
        with github_client() as client:
            token = verified_token(client, settings, permission)
            if not args.apply:
                label, present = check_issue(client, settings, token, snapshot)
                status = "already on GitHub" if present else "ready to add"
                print(f"Review {args.review_id} | issue #{snapshot['issue_number']} | {label} | {status}")
                return

            result = run_once(
                lambda job: deliver(client, settings, token, snapshot, job),
                review_id=args.review_id,
            )

        latest = load_review(args.review_id, settings.repository)
        print(f"Review {args.review_id} | {result or latest['state']}")
        if latest["last_error"]:
            print(latest["last_error"])
        if latest["state"] == "queued" and latest["attempts"] > 0:
            print(f"Retry after {latest['available_at'].isoformat()}")
    except (httpx.HTTPError, PermanentLabelError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
