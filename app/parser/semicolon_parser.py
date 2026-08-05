"""
Semicolon Parser.
Splits claim body text into individual ClaimElements using semicolons
as structural delimiters, following USPTO drafting conventions.
"""
import re
from typing import List
from app.parser.patterns import SEMICOLON_SPLIT


class SemicolonElement:
    """Intermediate representation of a semicolon-delimited element."""
    __slots__ = ("text", "order")

    def __init__(self, text: str, order: int):
        self.text = text
        self.order = order


class SemicolonParser:
    """
    Splits claim body on semicolons to produce individual elements.
    Does NOT split semicolons inside parentheses, chemical formulas, or URLs.
    """

    def parse(self, body_text: str) -> List[SemicolonElement]:
        """
        Splits body_text on structural semicolons and returns ordered elements.
        """
        if not body_text or not body_text.strip():
            return []

        # Split on semicolons not inside parentheses
        parts = SEMICOLON_SPLIT.split(body_text)

        elements: List[SemicolonElement] = []
        for i, part in enumerate(parts):
            cleaned = part.strip()
            
            # If this part starts with "and" or "or", we append it to the previous element
            match = re.match(r'^\s*(and|or)\s+', cleaned, flags=re.IGNORECASE)
            if match and elements:
                conjunction = match.group(1)
                elements[-1].text = f"{elements[-1].text} {conjunction}"
                cleaned = cleaned[match.end():].strip()
                
            if cleaned:
                elements.append(SemicolonElement(text=cleaned, order=i))

        return elements

    def has_semicolons(self, text: str) -> bool:
        """Returns True if the text contains structural semicolons."""
        return bool(SEMICOLON_SPLIT.search(text))
