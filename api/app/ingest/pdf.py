"""Text extraction with coordinates.

`pdftotext -bbox-layout` gives word boxes, which is the only reliable way to
recover the manual's two-column question layout: the plain `-layout` output
interleaves the columns line by line.
"""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\u00ad": "",
    "\u00a0": " ",
    "\u2009": " ",
    "\u202f": " ",
}

_HYPHEN_BREAK = re.compile(r"(\w)-$")
_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    for bad, good in LIGATURES.items():
        text = text.replace(bad, good)
    return _WS.sub(" ", text).strip()


def join_lines(lines: list[str]) -> str:
    """Join wrapped lines, repairing words split by a hyphen."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif _HYPHEN_BREAK.search(out) and line[:1].islower():
            out = out[:-1] + line
        else:
            out = f"{out} {line}"
    return normalise(out)


@dataclass(frozen=True)
class Block:
    x: float
    y: float
    x_max: float
    y_max: float
    text: str

    @property
    def single_token(self) -> str | None:
        return self.text if " " not in self.text and self.text else None


@dataclass(frozen=True)
class Page:
    number: int
    width: float
    height: float
    blocks: tuple[Block, ...]

    def body_blocks(self, margin_top: float = 60, margin_bottom: float = 40) -> list[Block]:
        """Blocks excluding running heads and page numbers."""
        return [
            b for b in self.blocks if b.y >= margin_top and b.y_max <= self.height - margin_bottom
        ]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def available() -> bool:
    return shutil_which("pdftotext") is not None


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def extract(pdf: Path) -> list[Page]:
    if not available():
        raise RuntimeError(
            "pdftotext not found. Install poppler-utils (the api image already has it)."
        )
    completed = subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_bbox(completed.stdout)


def parse_bbox(xml_text: str) -> list[Page]:
    root = ET.fromstring(xml_text)
    pages: list[Page] = []
    number = 0
    for element in root.iter():
        if _local(element.tag) != "page":
            continue
        number += 1
        width = float(element.attrib.get("width", "595"))
        height = float(element.attrib.get("height", "842"))
        blocks: list[Block] = []
        for block in element.iter():
            if _local(block.tag) != "block":
                continue
            lines: list[str] = []
            for line in block.iter():
                if _local(line.tag) != "line":
                    continue
                words = [(w.text or "") for w in line.iter() if _local(w.tag) == "word"]
                if words:
                    lines.append(" ".join(words))
            text = join_lines(lines)
            if not text:
                continue
            blocks.append(
                Block(
                    x=float(block.attrib.get("xMin", "0")),
                    y=float(block.attrib.get("yMin", "0")),
                    x_max=float(block.attrib.get("xMax", "0")),
                    y_max=float(block.attrib.get("yMax", "0")),
                    text=text,
                )
            )
        pages.append(Page(number=number, width=width, height=height, blocks=tuple(blocks)))
    return pages


def column_blocks(page: Page) -> list[list[Block]]:
    """Split a page's body into reading columns.

    The manual is two-column on question pages (gutter around the page centre)
    and single-column elsewhere. Blocks are assigned by their left edge, which
    is stable even when lines are justified.
    """
    body = page.body_blocks()
    if not body:
        return []
    midpoint = page.width / 2
    right = [b for b in body if b.x >= midpoint]
    # Few or no blocks on the right half: treat the page as single-column.
    if len(right) < 2:
        return [sorted(body, key=lambda b: (b.y, b.x))]
    left = [b for b in body if b.x < midpoint]
    return [
        sorted(left, key=lambda b: (round(b.y, 1), b.x)),
        sorted(right, key=lambda b: (round(b.y, 1), b.x)),
    ]
