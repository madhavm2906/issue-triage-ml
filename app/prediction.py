import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import joblib
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

from compare_body import title_and_body

CANDIDATE_DIR = (
    Path(__file__).resolve().parents[1] / "artifacts" / "issue_triage_body_candidate"
)

router = APIRouter(tags=["Predictions"])


class IssueText(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    body: str = ""


class Prediction(BaseModel):
    suggested_label: Literal["bug", "feature-request"]
    bug_score: float
    bug_cutoff: float


@lru_cache(maxsize=1)
def load_candidate():
    metadata = json.loads(
        (CANDIDATE_DIR / "metadata.json").read_text(encoding="utf-8")
    )
    model = joblib.load(CANDIDATE_DIR / "model.joblib")
    bug_column = list(model.classes_).index("bug")
    return model, bug_column, float(metadata["cutoff"])


@router.post("/predictions")
def predict_issue(issue: IssueText) -> Prediction:
    try:
        model, bug_column, cutoff = load_candidate()
    except FileNotFoundError as exc:
        raise HTTPException(503, "The saved model candidate is missing.") from exc

    text = title_and_body({"title": issue.title, "body": issue.body})
    bug_score = float(model.predict_proba([text])[0, bug_column])
    label = "bug" if bug_score >= cutoff else "feature-request"

    return Prediction(
        suggested_label=label,
        bug_score=bug_score,
        bug_cutoff=cutoff,
    )
