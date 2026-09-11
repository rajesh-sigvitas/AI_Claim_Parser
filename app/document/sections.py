"""
Splits a paginated document into its patent sections.

Headings in real drafts are inconsistent -- "DETAILED DESCRIPTION", "DETAILED DESCRIPTION
OF THE PREFERRED EMBODIMENTS", "Detailed Description of the Drawings" -- so matching is on
a normalised form of the line and anchored at its start.  A heading only counts when the
line is short: "The detailed description below explains ..." is prose, not a heading.

Two special cases decide where the claims begin and end:

* The claims start at the claim statement ("What is claimed is:"), which is also what the
  claim parser keys on, so both agree on the boundary.
* An ABSTRACT that follows the claims closes them.  Drafts put the abstract last, and
  without this the abstract would be analysed as though it were claim text.
"""
import re
from typing import List, Optional, Tuple

from app.document.models import Line, Page, Section, SectionKind

# Ordered: the first pattern that matches a line wins.
_HEADING_PATTERNS: List[Tuple[SectionKind, re.Pattern]] = [
    (SectionKind.CLAIMS, re.compile(
        r"^(what\s+is\s+claimed\s+is|we\s+claim|i\s+claim|the\s+invention\s+claimed\s+is"
        r"|what\s+is\s+claimed|claims?\s+what\s+is\s+claimed)\b", re.I)),
    (SectionKind.CLAIMS, re.compile(r"^claims?\s*:?\s*$", re.I)),
    (SectionKind.ABSTRACT, re.compile(r"^abstract(\s+of\s+the\s+disclosure)?\s*:?\s*$", re.I)),
    (SectionKind.BRIEF_DESCRIPTION, re.compile(
        r"^brief\s+description\s+of\s+the\s+(drawings?|figures?|several\s+views)", re.I)),
    (SectionKind.BRIEF_DESCRIPTION, re.compile(r"^description\s+of\s+the\s+(drawings?|figures?)", re.I)),
    (SectionKind.DETAILED_DESCRIPTION, re.compile(r"^detailed\s+description", re.I)),
    (SectionKind.DETAILED_DESCRIPTION, re.compile(
        r"^description\s+of\s+the\s+(preferred\s+)?(embodiments?|invention)", re.I)),
    (SectionKind.SUMMARY, re.compile(r"^summary(\s+of\s+the\s+(invention|disclosure))?\s*:?\s*$", re.I)),
    (SectionKind.BACKGROUND, re.compile(r"^background(\s+of\s+the\s+(invention|disclosure))?", re.I)),
    (SectionKind.FIELD, re.compile(r"^(technical\s+)?field(\s+of\s+the\s+(invention|disclosure))?\s*:?\s*$", re.I)),
    (SectionKind.FIELD, re.compile(r"^cross[- ]reference\s+to\s+related\s+applications?", re.I)),
]

# A heading is a short line; anything longer is a sentence that starts with the word.
_MAX_HEADING_WORDS = 12


def detect_sections(lines: List[Line], pages: Optional[List[Page]] = None) -> List[Section]:
    """
    Assigns every line to a section, in document order.

    Lines before the first recognised heading are front matter (cover sheet), and pages
    identified as drawing sheets become a DRAWINGS section regardless of their text.
    """
    if not lines:
        return []

    drawing_pages = {page.number for page in (pages or []) if is_drawing_sheet(page)}

    boundaries: List[Tuple[int, SectionKind, str]] = []
    for line in lines:
        if line.is_running_head or line.page in drawing_pages:
            continue
        kind = _heading_kind(line.text)
        if kind is None:
            continue
        # A second CLAIMS heading is the "CLAIM"/"What is claimed is:" pair, not a new
        # section; keep the first and let the statement line fall inside it.
        if boundaries and boundaries[-1][1] == kind and line.index - boundaries[-1][0] <= 2:
            continue
        boundaries.append((line.index, kind, line.text.strip()))

    sections: List[Section] = []

    first_boundary = boundaries[0][0] if boundaries else len(lines)
    if first_boundary > 0:
        sections.append(Section(
            kind=SectionKind.FRONT_MATTER, title="Front matter",
            start_index=0, end_index=first_boundary,
        ))

    for position, (line_index, kind, title) in enumerate(boundaries):
        end = boundaries[position + 1][0] if position + 1 < len(boundaries) else len(lines)
        sections.append(Section(
            kind=kind, title=title,
            start_index=line_index, end_index=end, heading_line=line_index,
        ))

    if drawing_pages:
        sections = _carve_out_drawings(sections, lines, drawing_pages)

    return _merge_adjacent(sections)


def is_drawing_sheet(page: Page) -> bool:
    """
    True when a page is a drawing sheet rather than prose.

    Drawing sheets are mostly picture and carry only labels: a figure caption, part
    numbers, a sheet number.  Either a large raster image or a page built from vector
    drawings with very little text qualifies.
    """
    if page.image_area_ratio >= 0.35 and page.word_count < 120:
        return True
    if page.drawing_count >= 40 and page.word_count < 120:
        return True
    if page.word_count and page.word_count < 40 and re.search(
        r"\bFIG(?:URE)?\.?\s*\d", page.text, re.I
    ):
        return True
    return False


def _carve_out_drawings(
    sections: List[Section], lines: List[Line], drawing_pages: set
) -> List[Section]:
    """Replaces the parts of sections that fall on drawing sheets with DRAWINGS spans."""
    spans: List[Section] = []
    for section in sections:
        current_kind = None
        start = section.start_index
        for index in range(section.start_index, section.end_index):
            kind = SectionKind.DRAWINGS if lines[index].page in drawing_pages else section.kind
            if current_kind is None:
                current_kind, start = kind, index
            elif kind != current_kind:
                spans.append(Section(
                    kind=current_kind,
                    title="Drawings" if current_kind == SectionKind.DRAWINGS else section.title,
                    start_index=start, end_index=index,
                    heading_line=section.heading_line if current_kind == section.kind else None,
                ))
                current_kind, start = kind, index
        if current_kind is not None:
            spans.append(Section(
                kind=current_kind,
                title="Drawings" if current_kind == SectionKind.DRAWINGS else section.title,
                start_index=start, end_index=section.end_index,
                heading_line=section.heading_line if current_kind == section.kind else None,
            ))
    return spans


def _merge_adjacent(sections: List[Section]) -> List[Section]:
    """Joins neighbouring spans of the same kind produced by the drawing carve-out."""
    merged: List[Section] = []
    for section in sections:
        if merged and merged[-1].kind == section.kind and merged[-1].end_index == section.start_index:
            merged[-1].end_index = section.end_index
            if merged[-1].heading_line is None:
                merged[-1].heading_line = section.heading_line
            continue
        merged.append(section)
    return merged


def _heading_kind(text: str) -> Optional[SectionKind]:
    stripped = re.sub(r"^[\[\(]?\s*\d+[\.\)\]]?\s*", "", text.strip())
    stripped = stripped.strip(" .:_-")
    if not stripped or len(stripped.split()) > _MAX_HEADING_WORDS:
        return None

    for kind, pattern in _HEADING_PATTERNS:
        if pattern.match(stripped):
            # "Background of the invention is described below" -- a sentence, not a heading.
            if kind != SectionKind.CLAIMS and len(stripped.split()) > 8:
                continue
            return kind
    return None
