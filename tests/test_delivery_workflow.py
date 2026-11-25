import json
import os
import unittest
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.database import engine
from app.github_label_sender import deliver, load_review
from app.label_worker import run_once
from app.main import app
from app.prediction import Prediction

PRIVATE = "test-owner/private-triage"
PUBLIC = "test-owner/public-triage"
TOKEN = "integration-test-token"


def github_issue(repository: str, issue_id: int) -> dict:
    return {
        "id": issue_id,
        "number": 1,
        "title": "Editor freezes on save",
        "body": "The editor stops responding after I save.",
        "state": "open",
        "labels": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "html_url": f"https://github.com/{repository}/issues/1",
    }


class DeliveryWorkflowTest(unittest.TestCase):
    def test_approval_delivers_only_to_configured_repository(self):
        self.assertEqual(engine.url.database, "triage_test", "Run scripts/test_workflow.sh.")
        private_issue = github_issue(PRIVATE, 101)
        public_issue = github_issue(PUBLIC, 102)
        label_writes = []

        def github_response(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            self.assertEqual(request.url.host, "api.github.com")
            if path == f"/repos/{PUBLIC}/issues":
                self.assertEqual(request.method, "GET")
                self.assertNotIn("Authorization", request.headers)
                return httpx.Response(200, json=[public_issue])

            self.assertEqual(request.headers.get("Authorization"), f"Bearer {TOKEN}")
            if path == f"/repos/{PRIVATE}/issues" and request.method == "GET":
                return httpx.Response(200, json=[private_issue])
            if path == f"/repos/{PRIVATE}/issues/1" and request.method == "GET":
                return httpx.Response(200, json=private_issue)
            if path == f"/repos/{PRIVATE}/issues/1/labels" and request.method == "POST":
                label_writes.append(json.loads(request.content))
                return httpx.Response(200, json=[{"name": "enhancement"}])
            self.fail(f"Unexpected GitHub request: {request.method} {path}")

        transport = httpx.MockTransport(github_response)
        make_client = partial(httpx.AsyncClient, transport=transport)
        self.enterContext(patch.dict(os.environ, {"GITHUB_TRIAGE_REPOSITORY": PRIVATE}))
        read_token = self.enterContext(patch("app.main.private_read_token", return_value=TOKEN))
        self.enterContext(patch("app.github.httpx.AsyncClient", side_effect=make_client))
        self.enterContext(patch(
            "app.reviews.predict_issue",
            return_value=Prediction(suggested_label="bug", bug_score=0.8, bug_cutoff=0.45),
        ))
        api = self.enterContext(TestClient(app))
        github = self.enterContext(httpx.Client(
            base_url="https://api.github.com", transport=transport
        ))
        settings = SimpleNamespace(repository=PRIVATE)

        def send(job):
            snapshot = load_review(job["review_id"], PRIVATE)
            deliver(github, settings, TOKEN, snapshot, job)

        def import_and_queue(repository, issue):
            result = api.post(f"/repositories/{repository}/import")
            self.assertEqual(result.raise_for_status().json()["written"], 1)
            result = api.post("/reviews", json={"issue_id": issue["id"]})
            return result.raise_for_status().json()["id"]

        public_review = import_and_queue(PUBLIC, public_issue)
        api.patch(f"/reviews/{public_review}", json={"final_label": "bug"}).raise_for_status()
        private_review = import_and_queue(PRIVATE, private_issue)
        read_token.assert_called_once_with(PRIVATE)

        self.assertIsNone(run_once(send, repository=PRIVATE))
        self.assertEqual(label_writes, [])

        decision = {"final_label": "feature-request"}
        api.patch(f"/reviews/{private_review}", json=decision).raise_for_status()
        api.patch(f"/reviews/{private_review}", json=decision).raise_for_status()
        self.assertEqual(run_once(send, repository=PRIVATE), "applied")
        self.assertIsNone(run_once(send, repository=PRIVATE))
        self.assertEqual(label_writes, [{"labels": ["enhancement"]}])

        private = api.get(f"/repositories/{PRIVATE}/issues").raise_for_status().json()
        public = api.get(f"/repositories/{PUBLIC}/issues").raise_for_status().json()
        self.assertEqual(private["issues"][0]["delivery_state"], "applied")
        self.assertTrue(private["issues"][0]["delivered_at"])
        self.assertEqual(public["issues"][0]["delivery_state"], "queued")
