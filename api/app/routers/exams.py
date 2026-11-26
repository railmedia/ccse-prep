from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_anon
from app.exam import service
from app.exam.service import EXAM_DURATION, ExamError
from app.models import ExamSession, Question
from app.rag.store import explanation_payload
from app.schemas.exam import (
    AttemptOut,
    CheckIn,
    CheckOut,
    CreateExamIn,
    ExamOut,
    Option,
    QuestionOut,
    ResultOut,
    SubmitIn,
)

router = APIRouter(prefix="/api", tags=["exams"])


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _question_out(question: Question) -> QuestionOut:
    return QuestionOut(
        id=question.id,
        task=question.task,
        kind=question.kind,
        stem=question.stem,
        options=[Option(**option) for option in question.options],
    )


def _exam_out(exam: ExamSession, questions: list[Question]) -> ExamOut:
    started = _aware(exam.started_at)
    timed = exam.mode != "practice"
    return ExamOut(
        id=str(exam.id),
        mode=exam.mode,
        feedback=exam.feedback,
        campaign_slot=exam.campaign_slot,
        started_at=started,
        expires_at=started + EXAM_DURATION if timed else None,
        duration_minutes=int(EXAM_DURATION.total_seconds() // 60) if timed else None,
        submitted_at=exam.submitted_at,
        # Note: no answers in the payload — scoring is server-side.
        questions=[_question_out(question) for question in questions],
    )


async def _owned_exam(session: AsyncSession, exam_id: uuid.UUID, anon_id: uuid.UUID) -> ExamSession:
    exam = await session.get(ExamSession, exam_id)
    if exam is None or exam.anon_id != anon_id:
        raise HTTPException(status_code=404, detail="exam not found")
    return exam


@router.post("/exams", response_model=ExamOut, status_code=201)
async def create_exam(
    payload: CreateExamIn,
    anon_id: uuid.UUID = Depends(current_anon),
    session: AsyncSession = Depends(get_session),
) -> ExamOut:
    try:
        exam = await service.create_exam(
            session,
            anon_id,
            payload.mode,
            task=payload.task,
            size=payload.size,
            whole_task=payload.all,
            feedback=payload.feedback,
        )
    except ExamError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    questions = await service.load_questions(session, exam)
    return _exam_out(exam, questions)


@router.get("/exams/{exam_id}", response_model=ExamOut)
async def get_exam(
    exam_id: uuid.UUID,
    anon_id: uuid.UUID = Depends(current_anon),
    session: AsyncSession = Depends(get_session),
) -> ExamOut:
    exam = await _owned_exam(session, exam_id, anon_id)
    questions = await service.load_questions(session, exam)
    return _exam_out(exam, questions)


@router.post("/exams/{exam_id}/submit", response_model=ResultOut)
async def submit_exam(
    exam_id: uuid.UUID,
    payload: SubmitIn,
    anon_id: uuid.UUID = Depends(current_anon),
    session: AsyncSession = Depends(get_session),
) -> ResultOut:
    exam = await _owned_exam(session, exam_id, anon_id)
    try:
        result = await service.submit_exam(session, exam, payload.answers, payload.duration_s)
    except ExamError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ResultOut(**result)


@router.post("/exams/{exam_id}/check", response_model=CheckOut)
async def check_answer(
    exam_id: uuid.UUID,
    payload: CheckIn,
    anon_id: uuid.UUID = Depends(current_anon),
    session: AsyncSession = Depends(get_session),
) -> CheckOut:
    """Reveal one verdict. Only for practice exams with immediate feedback."""
    exam = await _owned_exam(session, exam_id, anon_id)
    try:
        verdict = await service.check_answer(session, exam, payload.question_id, payload.selected)
    except ExamError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    explanation = await explanation_payload(session, payload.question_id)
    return CheckOut(**verdict, explanation=explanation)


@router.get("/attempts", response_model=list[AttemptOut])
async def attempts(
    anon_id: uuid.UUID = Depends(current_anon),
    session: AsyncSession = Depends(get_session),
) -> list[AttemptOut]:
    history = await service.attempt_history(session, anon_id)
    return [
        AttemptOut(
            id=str(exam.id),
            mode=exam.mode,
            campaign_slot=exam.campaign_slot,
            submitted_at=exam.submitted_at,
            score=exam.score,
            total=len(exam.question_ids),
            task_breakdown=exam.task_breakdown,
        )
        for exam in history
    ]


@router.get("/stats/hardest")
async def hardest(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    rows = await service.hardest_questions(session)
    return [
        {"question_id": qid, "attempts": total, "misses": missed} for qid, total, missed in rows
    ]
