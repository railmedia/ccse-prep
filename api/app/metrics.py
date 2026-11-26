"""Minimal Prometheus exposition.

A dependency-free counter/histogram registry: the API exposes `/metrics`, and
the numbers that matter (LLM calls, fallbacks, tokens, cost, latency) are
recorded where they happen rather than scraped from logs.
"""

from __future__ import annotations

import threading
from collections import defaultdict

Labels = tuple[tuple[str, str], ...]


def _labels(**labels: str) -> Labels:
    return tuple(sorted((key, str(value)) for key, value in labels.items()))


def _format(name: str, labels: Labels) -> str:
    if not labels:
        return name
    rendered = ",".join(f'{key}="{value}"' for key, value in labels)
    return f"{name}{{{rendered}}}"


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: defaultdict[tuple[str, Labels], float] = defaultdict(float)
        self._sums: defaultdict[tuple[str, Labels], float] = defaultdict(float)
        self._counts: defaultdict[tuple[str, Labels], int] = defaultdict(int)

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[(name, _labels(**labels))] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = (name, _labels(**labels))
        with self._lock:
            self._sums[key] += value
            self._counts[key] += 1

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{_format(name, labels)} {value:g}")
            for key, total in sorted(self._sums.items()):
                name, labels = key
                count = self._counts[key]
                lines.append(f"{_format(name + '_sum', labels)} {total:g}")
                lines.append(f"{_format(name + '_count', labels)} {count}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
