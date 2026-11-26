"""Parse the official manual into questions, an answer key and corpus chunks.

Pure functions: no database, no network. The job in ``app/jobs/ingest.py``
persists the result.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.ingest.pdf import Block, Page, column_blocks, join_lines, normalise

# Exam blueprint, verified against the 2026 manual (see docs/PLAN-V1.md §3).
QUESTION_RANGES: dict[int, tuple[int, int]] = {
    1: (1001, 1120),
    2: (2001, 2036),
    3: (3001, 3024),
    4: (4001, 4036),
    5: (5001, 5084),
}
EXPECTED_QUESTIONS = sum(high - low + 1 for low, high in QUESTION_RANGES.values())

_ID = re.compile(r"^([1-5])(\d{3})$")
_HEADER_TASK = re.compile(r"Tarea\s+([1-5])", re.IGNORECASE)
_SIDEBAR = re.compile(r"^(FIGURA|RECUERDA|IMPORTANTE)\b", re.IGNORECASE)


@dataclass
class ParsedQuestion:
    id: str
    task: int
    kind: str
    stem: str
    options: list[dict[str, str]]
    page: int
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "kind": self.kind,
            "stem": self.stem,
            "options": self.options,
            "page": self.page,
            "flags": self.flags,
        }


@dataclass
class ParsedChunk:
    id: str
    task: int
    section_path: list[str]
    page_from: int
    page_to: int
    body: str
    tokens: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "section_path": self.section_path,
            "page_from": self.page_from,
            "page_to": self.page_to,
            "body": self.body,
            "tokens": self.tokens,
        }


@dataclass
class ParseReport:
    questions: list[ParsedQuestion]
    answers: dict[str, str]
    chunks: list[ParsedChunk]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        per_task: dict[str, int] = {str(t): 0 for t in QUESTION_RANGES}
        for question in self.questions:
            per_task[str(question.task)] += 1
        return {
            "questions": len(self.questions),
            "expected": EXPECTED_QUESTIONS,
            "per_task": per_task,
            "answers": len(self.answers),
            "chunks": len(self.chunks),
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _question_id(token: str | None) -> str | None:
    if not token:
        return None
    match = _ID.match(token)
    if not match:
        return None
    task = int(match.group(1))
    value = int(token)
    low, high = QUESTION_RANGES[task]
    return token if low <= value <= high else None


def _tokens(blocks: Sequence[Block]) -> list[str]:
    out: list[str] = []
    for block in sorted(blocks, key=lambda b: (round(b.y, 1), b.x)):
        out.extend(block.text.split())
    return out


def _is_solution_page(page: Page) -> bool:
    # The answer key is the only place where the heading appears in caps; using
    # the marker is far more reliable than counting letters, because some
    # question pages print options as bare "a" cells too.
    if any("SOLUCIONES" in block.text for block in page.blocks):
        return True
    tokens = _tokens(page.blocks)
    ids = sum(1 for t in tokens if _question_id(t))
    letters = sum(1 for t in tokens if t in {"a", "b", "c"})
    has_options = any(" a. " in block.text or block.text.startswith("a. ") for block in page.blocks)
    return ids >= 8 and letters >= ids * 0.8 and not has_options


def _is_question_page(page: Page) -> bool:
    starts = sum(1 for block in page.blocks if _question_id(block.text.split(" ")[0]))
    return starts >= 3 or any(block.text.startswith("PREGUNTAS") for block in page.blocks)


def _header_task(page: Page) -> int | None:
    for block in page.blocks:
        if block.y > 70:
            continue
        match = _HEADER_TASK.search(block.text)
        if match:
            return int(match.group(1))
    return None


def _split_options(text: str) -> tuple[str, dict[str, str]]:
    """Split ``stem a. … b. … c. …`` into a stem and options."""
    found: dict[str, tuple[int, int]] = {}
    cursor = 0
    for letter in "abc":
        match = re.search(rf"(?:^|\s){letter}\.\s+", text[cursor:])
        if match is None:
            break
        start = cursor + match.start()
        end = cursor + match.end()
        found[letter] = (start, end)
        cursor = end
    if "a" not in found:
        return text, {}
    first = found["a"][0]
    stem = text[:first].strip()
    options: dict[str, str] = {}
    letters = list(found)
    for index, letter in enumerate(letters):
        start = found[letter][1]
        stop = found[letters[index + 1]][0] if index + 1 < len(letters) else len(text)
        options[letter] = text[start:stop].strip()
    return stem, options


def _parse_column(blocks: list[Block], page_number: int) -> list[ParsedQuestion]:
    parsed: list[ParsedQuestion] = []
    current_id: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current_id, buffer
        if current_id is None:
            return
        text = join_lines(buffer)
        stem, options = _split_options(text)
        flags: list[str] = []
        if len(options) == 2 and options.get("a", "").strip(".").lower().startswith(
            ("verdadero", "falso")
        ):
            kind = "vf"
        elif len(options) == 3:
            kind = "mc"
        else:
            kind = "invalid"
            flags.append(f"expected 3 options, found {len(options)}")
        parsed.append(
            ParsedQuestion(
                id=current_id,
                task=int(current_id[0]),
                kind=kind,
                stem=stem,
                options=[{"key": k, "text": v} for k, v in options.items()],
                page=page_number,
                flags=flags,
            )
        )
        current_id, buffer = None, []

    for block in blocks:
        # The id is usually its own block, but on some pages it shares a block
        # with the stem ("1001 España es… a. …").
        head, _, rest = block.text.partition(" ")
        candidate = _question_id(head)
        if candidate:
            flush()
            current_id = candidate
            if rest:
                buffer.append(rest)
            continue
        if current_id is not None:
            buffer.append(block.text)
    flush()
    return parsed


def parse_questions(pages: list[Page]) -> tuple[list[ParsedQuestion], list[str]]:
    errors: list[str] = []
    by_id: dict[str, ParsedQuestion] = {}
    for page in pages:
        if _is_solution_page(page) or not _is_question_page(page):
            continue
        for blocks in column_blocks(page):
            for question in _parse_column(blocks, page.number):
                if question.id in by_id:
                    errors.append(f"duplicate question {question.id} on page {page.number}")
                    continue
                by_id[question.id] = question

    questions = sorted(by_id.values(), key=lambda q: int(q.id))
    missing = [
        str(value)
        for task, (low, high) in QUESTION_RANGES.items()
        for value in range(low, high + 1)
        if str(value) not in by_id
    ]
    if missing:
        errors.append(f"missing {len(missing)} question ids: {', '.join(missing[:20])}")
    for question in questions:
        errors.extend(f"{question.id}: {flag}" for flag in question.flags)
    return questions, errors


def parse_answers(pages: list[Page]) -> tuple[dict[str, str], list[str]]:
    answers: dict[str, str] = {}
    errors: list[str] = []
    for page in pages:
        if not _is_solution_page(page):
            continue
        tokens = _tokens(page.blocks)
        for index, token in enumerate(tokens):
            question_id = _question_id(token)
            if not question_id or question_id in answers:
                continue
            following = tokens[index + 1] if index + 1 < len(tokens) else ""
            if following in {"a", "b", "c"}:
                answers[question_id] = following
            else:
                errors.append(f"{question_id}: no answer letter after id on page {page.number}")
    return answers, errors


def _looks_like_heading(text: str) -> bool:
    if len(text.split()) > 9 or text.endswith((".", ",", ";")):
        return False
    return text[:1].isupper()


def build_chunks(
    pages: list[Page],
    *,
    target_tokens: int = 340,
    overlap_tokens: int = 40,
) -> list[ParsedChunk]:
    """Merge body paragraphs into ~target_tokens chunks, by task and page span."""
    chunks: list[ParsedChunk] = []
    task: int | None = None
    section = ""
    start_section: str | None = None
    buffer: list[str] = []
    page_from: int | None = None
    page_to: int | None = None
    counter = 0

    def tokens(text: str) -> int:
        return len(text.split())

    def flush(next_page: int) -> None:
        nonlocal buffer, page_from, page_to, counter, start_section
        body = "\n\n".join(buffer).strip()
        if not body or page_from is None or page_to is None or task is None:
            buffer, page_from, page_to = [], None, None
            return
        counter += 1
        chunks.append(
            ParsedChunk(
                id=f"t{task}/{counter:03d}",
                task=task,
                section_path=[f"Tarea {task}"] + ([start_section] if start_section else []),
                page_from=page_from,
                page_to=page_to,
                body=body,
                tokens=tokens(body),
            )
        )
        tail = body.split()
        buffer = [" ".join(tail[-overlap_tokens:])] if overlap_tokens else []
        page_from = next_page
        page_to = next_page
        # The next chunk is labelled by the first heading it starts under, not
        # by whichever heading it happened to pass last.
        start_section = None

    for page in pages:
        if _is_solution_page(page) or _is_question_page(page):
            continue
        page_words = sum(len(block.text.split()) for block in page.body_blocks())
        if page_words < 60:
            continue
        page_text = " ".join(block.text for block in page.body_blocks())
        if "SUMARIO" in page_text or "ÍNDICE" in page_text:
            continue
        header_task = _header_task(page)
        if header_task is not None:
            task = header_task
        for blocks in column_blocks(page):
            for block in blocks:
                text = normalise(block.text)
                if not text or text.startswith("Instituto Cervantes") or _SIDEBAR.match(text):
                    continue
                if text.upper() == "PREGUNTAS":
                    continue
                if _question_id(block.single_token):
                    continue
                if _looks_like_heading(text):
                    section = text
                if page_from is None:
                    page_from = page.number
                page_to = page.number
                if start_section is None and section:
                    start_section = section
                buffer.append(text)
                if tokens(" ".join(buffer)) >= target_tokens:
                    flush(page.number)
    flush(page_to or 0)
    return chunks


def parse_manual(pages: list[Page]) -> ParseReport:
    questions, question_errors = parse_questions(pages)
    answers, answer_errors = parse_answers(pages)
    chunks = build_chunks(pages)
    warnings: list[str] = list(answer_errors)

    for question in questions:
        answer = answers.get(question.id)
        if answer is None:
            question_errors.append(f"{question.id}: missing answer")
        elif answer not in {option["key"] for option in question.options}:
            question_errors.append(f"{question.id}: answer {answer!r} not among options")

    valid_ids = {q.id for q in questions}
    for question_id in answers:
        if question_id not in valid_ids:
            warnings.append(f"{question_id}: answer present but question not parsed")

    if not chunks:
        question_errors.append("no corpus chunks produced")

    return ParseReport(
        questions=questions,
        answers=answers,
        chunks=chunks,
        errors=question_errors,
        warnings=warnings,
    )
