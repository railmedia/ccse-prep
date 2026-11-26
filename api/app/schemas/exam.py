from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Option(BaseModel):
    key: str
    text: str


class QuestionOut(BaseModel):
    id: str
    task: int
    kind: str
    stem: str
    options: list[Option]


class CreateExamIn(BaseModel):
    mode: Literal["campaign", "random", "practice"] = "campaign"
    task: int | None = Field(default=None, ge=1, le=5)
    size: int = Field(default=10, ge=1, le=200)
    # Practice only: take the whole task instead of a sample.
    all: bool = False
    # Practice only: reveal each verdict as it is answered.
    feedback: Literal["end", "immediate"] = "end"


class ExamOut(BaseModel):
    id: str
    mode: str
    feedback: str
    campaign_slot: int | None
    started_at: datetime
    # Null for practice: drills are untimed.
    expires_at: datetime | None
    duration_minutes: int | None
    submitted_at: datetime | None = None
    questions: list[QuestionOut]


class SubmitIn(BaseModel):
    answers: dict[str, str | None] = Field(default_factory=dict)
    duration_s: int = Field(default=0, ge=0)


class ReviewItem(BaseModel):
    question_id: str
    selected: str | None
    answer: str
    is_correct: bool


class ResultOut(BaseModel):
    exam_id: str
    score: int
    total: int
    passed: bool | None
    expired: bool
    task_breakdown: dict[str, Any]
    review: list[ReviewItem]


class AttemptOut(BaseModel):
    id: str
    mode: str
    campaign_slot: int | None
    submitted_at: datetime | None
    score: int | None
    total: int
    task_breakdown: dict[str, Any] | None


class CheckIn(BaseModel):
    question_id: str
    selected: Literal["a", "b", "c"]


class ExplanationOut(BaseModel):
    summary: str
    why_correct: str
    why_others_wrong: list[str]
    citations: list[dict[str, Any]]
    model: str
    confidence: float | None = None


class CheckOut(BaseModel):
    question_id: str
    selected: str
    is_correct: bool
    answer: str
    explanation: ExplanationOut | None = None
