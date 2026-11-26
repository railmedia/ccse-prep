from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.exam import service
from app.models import AnonUser, ExamSession, Question
from app.routers.exams import _exam_out

pytestmark = pytest.mark.integration


async def test_practice_all_returns_the_whole_task_untimed() -> None:
    async with SessionLocal() as session:
        pool_size = await session.scalar(select(func.count()).where(Question.task == 3))
        if not pool_size:
            pytest.skip("question bank not ingested")

        anon = AnonUser(id=uuid.uuid4())
        session.add(anon)
        await session.commit()

        exam = await service.create_exam(session, anon.id, "practice", task=3, whole_task=True)
        questions = await service.load_questions(session, exam)
        payload = _exam_out(exam, questions)

        assert len(exam.question_ids) == pool_size
        assert len(set(exam.question_ids)) == pool_size
        assert all(question_id.startswith("3") for question_id in exam.question_ids)
        assert payload.expires_at is None
        assert payload.duration_minutes is None
        assert len(payload.questions) == pool_size


async def test_practice_all_submits_without_expiring() -> None:
    async with SessionLocal() as session:
        anon = AnonUser(id=uuid.uuid4())
        session.add(anon)
        await session.commit()

        exam = await service.create_exam(session, anon.id, "practice", task=3, whole_task=True)
        questions = await service.load_questions(session, exam)
        answers = {question.id: question.answer for question in questions}
        result = await service.submit_exam(session, exam, answers, duration_s=90)

        assert result["score"] == len(questions)
        assert result["passed"] is None
        assert result["expired"] is False

        stored = await session.get(ExamSession, exam.id)
        assert stored is not None
        assert stored.submitted_at is not None
