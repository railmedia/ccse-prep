from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import SessionLocal
from app.exam import service
from app.exam.service import ExamError
from app.main import app
from app.models import AnonUser, Question

pytestmark = pytest.mark.integration


async def test_immediate_feedback_is_rejected_outside_practice() -> None:
    async with SessionLocal() as session:
        anon = AnonUser(id=uuid.uuid4())
        session.add(anon)
        await session.commit()
        for mode in ("campaign", "random"):
            with pytest.raises(ExamError):
                await service.create_exam(session, anon.id, mode, feedback="immediate")


async def test_check_answer_reveals_only_this_exams_questions(seeded_bank: None) -> None:
    async with SessionLocal() as session:
        anon = AnonUser(id=uuid.uuid4())
        session.add(anon)
        await session.commit()

        exam = await service.create_exam(
            session, anon.id, "practice", task=3, whole_task=True, feedback="immediate"
        )
        question = await session.get(Question, exam.question_ids[0])
        assert question is not None

        right = await service.check_answer(session, exam, question.id, question.answer)
        assert right["is_correct"] is True
        assert right["answer"] == question.answer

        wrong_key = next(key for key in {"a", "b", "c"} if key != question.answer)
        wrong = await service.check_answer(session, exam, question.id, wrong_key)
        assert wrong["is_correct"] is False

        with pytest.raises(ExamError):
            await service.check_answer(session, exam, "9999", "a")


async def test_check_refuses_exams_without_immediate_feedback(
    seeded_bank: None,
) -> None:
    async with SessionLocal() as session:
        anon = AnonUser(id=uuid.uuid4())
        session.add(anon)
        await session.commit()

        exam = await service.create_exam(session, anon.id, "random")
        with pytest.raises(ExamError):
            await service.check_answer(session, exam, exam.question_ids[0], "a")


async def test_check_endpoint_rejects_another_users_exam(seeded_bank: None) -> None:
    async with SessionLocal() as session:
        anon = AnonUser(id=uuid.uuid4())
        session.add(anon)
        await session.commit()
        exam = await service.create_exam(
            session, anon.id, "practice", task=3, whole_task=True, feedback="immediate"
        )
        question_id = exam.question_ids[0]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/exams/{exam.id}/check",
            json={"question_id": question_id, "selected": "a"},
        )
    assert response.status_code == 404


async def test_check_endpoint_reports_feedback_mode(seeded_bank: None) -> None:
    async with SessionLocal() as session:
        has_explanations = await session.scalar(select(Question.id).limit(1))
        if not has_explanations:
            pytest.skip("question bank not ingested")
        anon = AnonUser(id=uuid.uuid4())
        session.add(anon)
        await session.commit()
        exam = await service.create_exam(
            session, anon.id, "practice", task=3, whole_task=True, feedback="immediate"
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("ccse_anon", str(anon.id))
        created = await client.get(f"/api/exams/{exam.id}")
        assert created.status_code == 200
        payload = created.json()
        assert payload["feedback"] == "immediate"
        assert payload["expires_at"] is None

        response = await client.post(
            f"/api/exams/{exam.id}/check",
            json={"question_id": exam.question_ids[0], "selected": "a"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["question_id"] == exam.question_ids[0]
    assert body["is_correct"] in {True, False}
    assert "answer" in body
    # Synthetic questions have no precomputed explanation; the key must exist.
    assert "explanation" in body
