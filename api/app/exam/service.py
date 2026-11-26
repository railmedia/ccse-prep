"""Exam lifecycle: creation and server-side scoring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exam import sampler
from app.exam.sampler import QUOTA
from app.models import ExamAnswer, ExamSession, Question

EXAM_DURATION = timedelta(minutes=45)
GRACE = timedelta(seconds=10)


class ExamError(Exception):
    """Domain error surfaced as 4xx by the router."""


async def _pools(session: AsyncSession) -> dict[int, list[str]]:
    rows = await session.execute(select(Question.id, Question.task).order_by(Question.id))
    pools: dict[int, list[str]] = {task: [] for task in QUOTA}
    for question_id, task in rows:
        pools.setdefault(task, []).append(question_id)
    if any(len(pools[task]) < QUOTA[task] for task in QUOTA):
        raise ExamError("question bank is empty or incomplete; run make ingest")
    return pools


async def _next_campaign_slot(session: AsyncSession, anon_id: uuid.UUID) -> int:
    rows = await session.execute(
        select(ExamSession.campaign_slot).where(
            ExamSession.anon_id == anon_id,
            ExamSession.mode == "campaign",
            ExamSession.campaign_slot.is_not(None),
        )
    )
    used = {slot for (slot,) in rows}
    for slot in range(1, sampler.SLOTS + 1):
        if slot not in used:
            return slot
    raise ExamError("campaign complete: all 12 mock exams have been taken")


async def create_exam(
    session: AsyncSession,
    anon_id: uuid.UUID,
    mode: str,
    *,
    task: int | None = None,
    size: int = 10,
    whole_task: bool = False,
    feedback: str = "end",
) -> ExamSession:
    if feedback not in {"end", "immediate"}:
        raise ExamError(f"unknown feedback mode {feedback!r}")
    if feedback == "immediate" and mode != "practice":
        raise ExamError("immediate feedback is only available in practice mode")

    pools = await _pools(session)
    slot: int | None = None

    if mode == "campaign":
        slot = await _next_campaign_slot(session, anon_id)
        question_ids = sampler.campaign_exam(pools, slot)
    elif mode == "random":
        question_ids = sampler.random_exam(pools)
    elif mode == "practice":
        if task not in QUOTA:
            raise ExamError("practice mode needs a task between 1 and 5")
        question_ids = (
            sampler.all_questions(pools, task)
            if whole_task
            else sampler.practice_exam(pools, task, max(1, size))
        )
    else:
        raise ExamError(f"unknown mode {mode!r}")

    exam = ExamSession(
        anon_id=anon_id,
        mode=mode,
        feedback=feedback,
        campaign_slot=slot,
        question_ids=question_ids,
    )
    session.add(exam)
    await session.commit()
    await session.refresh(exam)
    return exam


async def load_questions(session: AsyncSession, exam: ExamSession) -> list[Question]:
    rows = await session.execute(select(Question).where(Question.id.in_(exam.question_ids)))
    by_id = {question.id: question for question in rows.scalars()}
    return [by_id[qid] for qid in exam.question_ids if qid in by_id]


async def submit_exam(
    session: AsyncSession,
    exam: ExamSession,
    answers: dict[str, str | None],
    duration_s: int,
) -> dict[str, Any]:
    if exam.submitted_at is not None:
        raise ExamError("exam already submitted")

    questions = await load_questions(session, exam)
    correct_by_id = {question.id: question.answer for question in questions}
    task_by_id = {question.id: question.task for question in questions}

    score = 0
    breakdown: dict[str, dict[str, int]] = {
        str(task): {"correct": 0, "total": quota} for task, quota in QUOTA.items()
    }
    if exam.mode == "practice":
        task = next(iter(task_by_id.values()), None)
        if task is not None:
            breakdown = {str(task): {"correct": 0, "total": len(questions)}}

    review: list[dict[str, Any]] = []
    for question in questions:
        selected = answers.get(question.id)
        selected = selected if selected in {"a", "b", "c"} else None
        is_correct = selected is not None and selected == correct_by_id[question.id]
        if is_correct:
            score += 1
            breakdown[str(question.task)]["correct"] += 1
        session.add(
            ExamAnswer(
                exam_id=exam.id,
                question_id=question.id,
                selected=selected,
                is_correct=is_correct,
            )
        )
        review.append(
            {
                "question_id": question.id,
                "selected": selected,
                "answer": correct_by_id[question.id],
                "is_correct": is_correct,
            }
        )

    now = datetime.now(UTC)
    started = exam.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed = now - started

    exam.submitted_at = now
    exam.score = score
    exam.task_breakdown = breakdown
    exam.duration_s = max(0, min(duration_s, int(elapsed.total_seconds()) + 60))

    await session.commit()
    await session.refresh(exam)

    return {
        "exam_id": str(exam.id),
        "score": score,
        "total": len(questions),
        "passed": score >= 15 if exam.mode != "practice" else None,
        "expired": exam.mode != "practice" and elapsed > EXAM_DURATION + GRACE,
        "task_breakdown": breakdown,
        "review": review,
    }


async def check_answer(
    session: AsyncSession,
    exam: ExamSession,
    question_id: str,
    selected: str,
) -> dict[str, Any]:
    """Reveal one verdict, for a question that belongs to this exam.

    The membership check is the point: without it this would be an answer
    oracle over the whole bank.
    """
    if exam.feedback != "immediate":
        # Otherwise this endpoint would leak the key in timed mock exams.
        raise ExamError("this exam does not use immediate feedback")
    if exam.submitted_at is not None:
        raise ExamError("exam already submitted")
    if question_id not in exam.question_ids:
        raise ExamError("question does not belong to this exam")
    if selected not in {"a", "b", "c"}:
        raise ExamError("selected must be one of a, b, c")

    question = await session.get(Question, question_id)
    if question is None:
        raise ExamError("question not found")

    return {
        "question_id": question.id,
        "selected": selected,
        "is_correct": selected == question.answer,
        "answer": question.answer,
    }


async def attempt_history(session: AsyncSession, anon_id: uuid.UUID) -> list[ExamSession]:
    rows = await session.execute(
        select(ExamSession)
        .where(ExamSession.anon_id == anon_id, ExamSession.submitted_at.is_not(None))
        .order_by(ExamSession.submitted_at.desc())
        .limit(20)
    )
    return list(rows.scalars())


async def hardest_questions(session: AsyncSession, limit: int = 10) -> list[tuple[str, int, int]]:
    """Most-missed questions across all users: (question_id, attempts, misses)."""
    misses = func.count().filter(~ExamAnswer.is_correct).label("misses")
    attempts = func.count().label("attempts")
    rows = await session.execute(
        select(ExamAnswer.question_id, attempts, misses)
        .group_by(ExamAnswer.question_id)
        .having(attempts >= 3)
        .order_by(misses.desc())
        .limit(limit)
    )
    return [(str(qid), int(total), int(missed or 0)) for qid, total, missed in rows]
