"""
The whole-document model every Claim Master module reads from.

The claim pipeline deliberately throws the specification away -- ``ClaimStatementDetector``
returns only what follows "What is claimed is:".  That is right for claim parsing and
useless for the rest of the report: sections IV to VIII analyse the specification, and
every one of them cites a position, "[Page 7, line 11]".

So this model keeps the document as it is *rendered*: pages of numbered lines.  Page and
line numbers are the rendered ones (a .docx is laid out by LibreOffice first), because
that is the only numbering a reader can check against their own copy.  Every finding in
the report carries a :class:`LineRef` into this structure, and the renderer turns that
into a citation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


class SectionKind(str, Enum):
    """The parts of a patent application the report treats differently."""

    FRONT_MATTER = "FRONT_MATTER"           # cover sheet: title, inventors, docket
    FIELD = "FIELD"
    BACKGROUND = "BACKGROUND"
    SUMMARY = "SUMMARY"
    BRIEF_DESCRIPTION = "BRIEF_DESCRIPTION"  # brief description of the drawings
    DETAILED_DESCRIPTION = "DETAILED_DESCRIPTION"
    CLAIMS = "CLAIMS"
    ABSTRACT = "ABSTRACT"
    DRAWINGS = "DRAWINGS"                    # figure sheets
    OTHER = "OTHER"

    @property
    def is_specification(self) -> bool:
        """
        True for the sections that count as "the specification" for support checks.

        The claims are not their own antecedent basis, and neither the cover sheet nor
        the drawing sheets are prose, so support for a claim term has to come from the
        body of the description.
        """
        return self in _SPECIFICATION_SECTIONS


_SPECIFICATION_SECTIONS = frozenset({
    SectionKind.FIELD,
    SectionKind.BACKGROUND,
    SectionKind.SUMMARY,
    SectionKind.BRIEF_DESCRIPTION,
    SectionKind.DETAILED_DESCRIPTION,
    SectionKind.ABSTRACT,
})


@dataclass
class Line:
    """One rendered line of text, and where a reader will find it."""

    page: int                    # 1-based page number as rendered
    number: int                  # 1-based line number within that page
    text: str
    index: int = 0               # position in PatentDocument.lines, filled by the loader
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    section: SectionKind = SectionKind.OTHER
    is_running_head: bool = False  # repeated header/footer, excluded from prose

    @property
    def citation(self) -> str:
        """The form every report section uses: ``[Page 7, line 11]``."""
        return f"[Page {self.page}, line {self.number}]"

    def __len__(self) -> int:
        return len(self.text)


@dataclass
class LineRef:
    """A span of characters inside one line -- what a finding points at."""

    line_index: int
    char_start: int = 0
    char_end: int = 0

    def resolve(self, document: "PatentDocument") -> Optional[Line]:
        if 0 <= self.line_index < len(document.lines):
            return document.lines[self.line_index]
        return None


@dataclass
class Page:
    """A rendered page: its text lines plus enough geometry to spot a drawing sheet."""

    number: int
    lines: List[Line] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    image_count: int = 0
    image_area_ratio: float = 0.0
    drawing_count: int = 0

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def word_count(self) -> int:
        return sum(len(line.text.split()) for line in self.lines)


@dataclass
class Section:
    """A contiguous run of lines under one heading."""

    kind: SectionKind
    title: str
    start_index: int             # inclusive index into PatentDocument.lines
    end_index: int               # exclusive
    heading_line: Optional[int] = None

    def lines(self, document: "PatentDocument") -> List[Line]:
        return document.lines[self.start_index:self.end_index]

    def text(self, document: "PatentDocument") -> str:
        return "\n".join(line.text for line in self.lines(document))

    def __contains__(self, line_index: int) -> bool:
        return self.start_index <= line_index < self.end_index


@dataclass
class FigurePart:
    """A part number read off a drawing sheet."""

    number: str                  # "104-1"; kept as text because of the suffix forms
    confidence: float = 0.0
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class Figure:
    """One drawing sheet, with whatever the OCR could read off it."""

    sheet: int                   # 1-based sheet number among the drawings
    page: int                    # page in the document as a whole
    labels: List[str] = field(default_factory=list)     # "FIG. 1A", "FIG. 2"
    parts: List[FigurePart] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)   # "Fonts may be too small: 9pt."
    image_path: Optional[str] = None

    @property
    def part_numbers(self) -> List[str]:
        return [p.number for p in self.parts]


class PatentDocument:
    """
    Everything the report needs about one application, in one object.

    Holds the rendered pages, the flat line list every citation indexes into, the
    section map, the drawing sheets, and the parsed :class:`~app.models.document.ClaimDocument`
    produced by the existing claim pipeline.
    """

    def __init__(
        self,
        filename: str = "",
        pages: Optional[List[Page]] = None,
        sections: Optional[List[Section]] = None,
        figures: Optional[List[Figure]] = None,
        claims=None,
        metadata: Optional[Dict[str, object]] = None,
    ):
        self.filename = filename
        self.pages: List[Page] = pages or []
        self.sections: List[Section] = sections or []
        self.figures: List[Figure] = figures or []
        self.claims = claims                      # ClaimDocument | None
        self.metadata: Dict[str, object] = metadata or {}

        self.lines: List[Line] = [line for page in self.pages for line in page.lines]
        for position, line in enumerate(self.lines):
            line.index = position

    # -- construction helpers ----------------------------------------------

    def reindex(self) -> None:
        """Rebuilds the flat line list after pages have been edited."""
        self.lines = [line for page in self.pages for line in page.lines]
        for position, line in enumerate(self.lines):
            line.index = position

    def assign_sections(self) -> None:
        """Stamps each line with the section it falls in, for cheap lookups later."""
        for section in self.sections:
            for line in self.lines[section.start_index:section.end_index]:
                line.section = section.kind

    # -- text views ---------------------------------------------------------

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def section(self, kind: SectionKind) -> Optional[Section]:
        for section in self.sections:
            if section.kind == kind:
                return section
        return None

    def section_lines(self, *kinds: SectionKind) -> List[Line]:
        wanted = set(kinds)
        return [line for line in self.lines if line.section in wanted]

    def specification_lines(self, include_running_heads: bool = False) -> List[Line]:
        """
        Every prose line of the specification, claims and cover sheet excluded.

        This is the corpus for support checks (IV), part names (V), acronyms (VII)
        and language warnings (VIII).
        """
        return [
            line for line in self.lines
            if line.section.is_specification
            and (include_running_heads or not line.is_running_head)
        ]

    @property
    def specification_text(self) -> str:
        return "\n".join(line.text for line in self.specification_lines())

    def iter_lines(
        self, kinds: Optional[Iterable[SectionKind]] = None, skip_running_heads: bool = True
    ) -> Iterator[Line]:
        wanted = set(kinds) if kinds else None
        for line in self.lines:
            if skip_running_heads and line.is_running_head:
                continue
            if wanted is not None and line.section not in wanted:
                continue
            yield line

    # -- citations ----------------------------------------------------------

    def citation(self, line_index: int) -> str:
        if 0 <= line_index < len(self.lines):
            return self.lines[line_index].citation
        return ""

    def snippet(self, line_index: int, limit: int = 110, join: int = 2) -> str:
        """
        The quoted text a citation shows.

        The report quotes the start of the sentence and trails off with "..." when it
        runs long, so a reader can find the passage without the report reprinting it.
        """
        if not (0 <= line_index < len(self.lines)):
            return ""
        parts = [self.lines[line_index].text.strip()]
        for offset in range(1, join + 1):
            following = line_index + offset
            if following >= len(self.lines):
                break
            if self.lines[following].is_running_head:
                continue
            if len(" ".join(parts)) >= limit:
                break
            parts.append(self.lines[following].text.strip())

        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0]
        return f"{cut} ..."

    def __repr__(self) -> str:
        return (
            f"PatentDocument({self.filename!r}, pages={len(self.pages)}, "
            f"lines={len(self.lines)}, sections={len(self.sections)}, "
            f"figures={len(self.figures)})"
        )
