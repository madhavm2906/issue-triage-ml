from urllib.parse import quote

import httpx
from fastapi import HTTPException


def normalize_issue(item: dict) -> dict:
    return {
        "github_id": item["id"],
        "number": item["number"],
        "title": item["title"],
        "body": item.get("body") or "",
        "state": item["state"],
        "labels": [label["name"] for label in item.get("labels", [])],
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "url": item["html_url"],
    }


async def list_repository_issues(
    owner: str,
    repo: str,
    state: str,
    page: int,
    per_page: int,
    *,
    labels: str | None = None,
    token: str | None = None,
) -> dict:
    url = (
        "https://api.github.com/repos/"
        f"{quote(owner, safe='')}/{quote(repo, safe='')}/issues"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "issue-triage-ml",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    params: dict[str, str | int] = {
        "state": state,
        "page": page,
        "per_page": per_page,
        "sort": "created",
        "direction": "desc",
    }
    if labels is not None:
        params["labels"] = labels

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=headers,
            follow_redirects=token is None,
        ) as client:
            response = await client.get(url, params=params)
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "GitHub request timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not connect to GitHub.") from exc

    if response.status_code == 404:
        raise HTTPException(404, "Repository not found or not accessible.")

    if response.status_code in (403, 429):
        raise HTTPException(
            response.status_code,
            "GitHub denied the request or applied a rate limit.",
        )

    if response.status_code != 200:
        raise HTTPException(502, "GitHub returned an unexpected response.")

    issues = [
        normalize_issue(item)
        for item in response.json()
        if "pull_request" not in item
    ]

    return {
        "repository": f"{owner}/{repo}",
        "page": page,
        "per_page": per_page,
        "returned": len(issues),
        "has_next_page": "next" in response.links,
        "issues": issues,
    }
