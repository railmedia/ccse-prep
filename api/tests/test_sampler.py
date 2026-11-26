from __future__ import annotations

from app.exam import sampler


def _pools() -> dict[int, list[str]]:
    sizes = {1: 120, 2: 36, 3: 24, 4: 36, 5: 84}
    return {task: [f"{task}{index:03d}" for index in range(size)] for task, size in sizes.items()}


def test_campaign_has_exam_blueprint() -> None:
    pools = _pools()
    for slot in range(1, sampler.SLOTS + 1):
        exam = sampler.campaign_exam(pools, slot)
        assert len(exam) == sampler.TOTAL
        for task, quota in sampler.QUOTA.items():
            assert sum(1 for question_id in exam if int(question_id[0]) == task) == quota


def test_twelve_campaign_exams_are_disjoint_and_cover_everything() -> None:
    pools = _pools()
    seen: set[str] = set()
    for slot in range(1, sampler.SLOTS + 1):
        exam = set(sampler.campaign_exam(pools, slot))
        assert not seen & exam, f"slot {slot} overlaps a previous exam"
        seen |= exam
    assert len(seen) == 300


def test_random_exam_keeps_the_blueprint() -> None:
    exam = sampler.random_exam(_pools())
    assert len(exam) == sampler.TOTAL
    for task, quota in sampler.QUOTA.items():
        assert sum(1 for question_id in exam if int(question_id[0]) == task) == quota


def test_practice_is_capped_by_pool_size() -> None:
    exam = sampler.practice_exam(_pools(), task=3, size=99)
    assert len(exam) == 24


def test_all_questions_returns_the_whole_pool_in_id_order() -> None:
    pools = _pools()
    ids = sampler.all_questions(pools, 3)
    assert len(ids) == 24
    assert ids == sorted(ids, key=int)
    assert len(set(ids)) == 24
