"""Batch jobs.

Each job is a container: `docker compose run --rm api python -m app.jobs.<name>`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import delete, select

from app.db import SessionLocal, dispose
from app.ingest.parse import parse_manual
from app.ingest.pdf import extract
from app.models import Chunk, Document, Question


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


async def ingest(pdf: Path, year: int, force: bool, allow_errors: bool) -> dict[str, object]:
    if not pdf.exists():
        raise SystemExit(f"PDF not found: {pdf}")

    sha = _sha256(pdf)
    async with SessionLocal() as session:
        existing = await session.scalar(select(Document).where(Document.sha256 == sha))
        if existing is not None and not force:
            return {
                "status": "skipped",
                "reason": "already ingested",
                "document_id": str(existing.id),
                "sha256": sha,
            }

        pages = extract(pdf)
        report = parse_manual(pages)
        summary = report.summary()
        if report.errors and not allow_errors:
            return {"status": "failed", "errors": report.errors, **summary}

        if existing is not None:
            await session.delete(existing)
            await session.execute(delete(Question))
            await session.flush()

        document = Document(source_year=year, filename=pdf.name, sha256=sha, pages=len(pages))
        session.add(document)
        await session.flush()

        for chunk in report.chunks:
            session.add(
                Chunk(
                    id=chunk.id,
                    document_id=document.id,
                    task=chunk.task,
                    section_path=chunk.section_path,
                    page_from=chunk.page_from,
                    page_to=chunk.page_to,
                    body=chunk.body,
                    token_count=chunk.tokens,
                )
            )

        for parsed in report.questions:
            session.add(
                Question(
                    id=parsed.id,
                    task=parsed.task,
                    kind=parsed.kind,
                    stem=parsed.stem,
                    options=parsed.options,
                    answer=report.answers[parsed.id],
                    source_page=parsed.page,
                    source_year=year,
                    notes="; ".join(parsed.flags) or None,
                )
            )

        await session.commit()

    return {
        "status": "ok",
        "document_id": str(document.id),
        "sha256": sha,
        **summary,
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    try:
        return await ingest(
            args.pdf, year=args.year, force=args.force, allow_errors=args.allow_errors
        )
    finally:
        # Dispose inside the same loop: the pool is bound to this event loop.
        await dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest the CCSE manual")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--force", action="store_true", help="re-ingest even if sha matches")
    parser.add_argument("--allow-errors", action="store_true")
    args = parser.parse_args(argv)

    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"ok", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
