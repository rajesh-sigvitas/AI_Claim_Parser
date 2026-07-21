"""
Enumeration Detector.
Detects alphabetic, roman, and numeric enumerations within claim body text
and assigns indentation levels for hierarchy reconstruction.
"""
import re
from typing import List, Optional, Tuple
from app.parser.patterns import (
    ENUM_ALPHA_LOWER,
    ENUM_ALPHA_UPPER,
    ENUM_ROMAN,
    ENUM_NUMERIC,
    INLINE_ENUM_PATTERN,
)


class EnumerationItem:
    """Represents a single detected enumeration item."""
    __slots__ = ("marker", "text", "level", "enum_type")

    def __init__(self, marker: str, text: str, level: int, enum_type: str):
        self.marker = marker
        self.text = text
        self.level = level
        self.enum_type = enum_type  # "alpha_lower", "alpha_upper", "roman", "numeric"


class EnumerationDetector:
    """
    Detects enumeration markers in claim body text.
    Assigns hierarchy levels based on patent drafting conventions:
        Level 0: (a), (b), (c)  — lowercase alpha
        Level 1: (i), (ii)       — roman
        Level 2: (A), (B)        — uppercase alpha
        Level 3: (1), (2)        — numeric
    """

    # Hierarchy level assignments per convention
    _LEVEL_MAP = {
        "alpha_lower": 0,
        "roman": 1,
        "alpha_upper": 2,
        "numeric": 3,
    }

    def detect_inline(self, text: str) -> List[EnumerationItem]:
        """
        Splits text that contains inline enumerations like:
        '(a) receiving data; (b) processing the data; and (c) transmitting'
        Returns a list of EnumerationItems.
        """
        # Find all inline markers and their positions
        markers: List[Tuple[int, str, str]] = []  # (pos, marker, enum_type)

        for m in re.finditer(r'\(([a-z])\)', text):
            markers.append((m.start(), m.group(0), "alpha_lower"))
        for m in re.finditer(r'\(([A-Z])\)', text):
            markers.append((m.start(), m.group(0), "alpha_upper"))
        for m in re.finditer(r'\((i{1,3}|iv|vi{0,3}|ix|x)\)', text, re.IGNORECASE):
            # Disambiguate: if single letter 'i' already matched as alpha, skip
            # Roman numerals are only considered roman if they have >1 char or are 'i'
            markers.append((m.start(), m.group(0), "roman"))
        for m in re.finditer(r'\((\d+)\)', text):
            markers.append((m.start(), m.group(0), "numeric"))

        if not markers:
            return []

        # Sort by position
        markers.sort(key=lambda x: x[0])

        # Deduplicate overlapping matches (prefer first match at each position)
        seen_positions = set()
        unique_markers = []
        for pos, marker, etype in markers:
            if pos not in seen_positions:
                seen_positions.add(pos)
                unique_markers.append((pos, marker, etype))
        markers = unique_markers

        items: List[EnumerationItem] = []
        for idx, (pos, marker, etype) in enumerate(markers):
            # Text runs from after this marker to the start of the next marker
            start = pos + len(marker)
            if idx + 1 < len(markers):
                end = markers[idx + 1][0]
            else:
                end = len(text)

            item_text = text[start:end].strip()
            
            level = self._LEVEL_MAP.get(etype, 0)
            items.append(EnumerationItem(
                marker=marker,
                text=item_text.strip(),
                level=level,
                enum_type=etype,
            ))

        return items

    def has_enumerations(self, text: str) -> bool:
        """Returns True if the text contains any enumeration markers."""
        return bool(re.search(r'\([a-z]\)|\([A-Z]\)|\(\d+\)|\(i{1,3}\)|\(iv\)|\(vi{0,3}\)', text))
