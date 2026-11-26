"""Blueprint-faithful exam sampling.

The bank's pools are exactly 12 times their exam quota, so campaign mode can carve
the whole bank into 12 disjoint exams. Random mode keeps the same task mix but
samples independently.
"""

from __future__ import annotations

import random

QUOTA: dict[int, int] = {1: 10, 2: 3, 3: 2, 4: 3, 5: 7}
SLOTS = 12
TOTAL = sum(QUOTA.values())  # 25


def _shuffled_pool(ids: list[str], task: int, seed: int) -> list[str]:
    pool = sorted(ids)
    random.Random(f"ccse-{seed}-{task}").shuffle(pool)
    return pool


def campaign_exam(pools: dict[int, list[str]], slot: int, seed: int = 2026) -> list[str]:
    """Return the question ids for campaign slot ``slot`` (1..12)."""
    if not 1 <= slot <= SLOTS:
        raise ValueError(f"slot must be between 1 and {SLOTS}")
    chosen: list[str] = []
    for task, quota in QUOTA.items():
        pool = _shuffled_pool(pools[task], task, seed)
        start = (slot - 1) * quota
        chunk = pool[start : start + quota]
        if len(chunk) != quota:
            raise ValueError(f"task {task} pool too small for slot {slot}")
        chosen.extend(chunk)
    return chosen


def random_exam(pools: dict[int, list[str]], rng: random.Random | None = None) -> list[str]:
    source = rng or random.SystemRandom()
    chosen: list[str] = []
    for task, quota in QUOTA.items():
        chosen.extend(source.sample(pools[task], quota))
    return chosen


def practice_exam(
    pools: dict[int, list[str]], task: int, size: int, rng: random.Random | None = None
) -> list[str]:
    source = rng or random.SystemRandom()
    pool = pools[task]
    return source.sample(pool, min(size, len(pool)))


def all_questions(pools: dict[int, list[str]], task: int) -> list[str]:
    """Whole task, in id order so a long drill has a stable shape."""
    if task not in pools:
        raise ValueError(f"unknown task {task}")
    return sorted(pools[task], key=int)
