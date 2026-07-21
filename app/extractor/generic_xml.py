"""
Generic XML Extractor.
Handles non-USPTO XML documents (WIPO, EPO, Google Patents, Lens.org, etc.).
Extracts visible claim text from XML and passes it to the Rule Engine.
"""
from typing import List
from bs4 import BeautifulSoup, Tag
from loguru import logger


class GenericXMLExtractor:
    """
    Extracts claim text from non-USPTO XML formats.
    Inspects the XML tree looking for claim-like structures
    using configurable tag name matching.
    """

    # Known claim-related tag names across standards
    _CLAIM_TAG_NAMES = {
        "claim", "claims", "claim-text", "claim-body",
        "patcit", "claim-statement",
        # EPO / WIPO
        "cl-claim", "cl-claim-text",
    }

    def extract(self, raw_input: bytes) -> str:
        """
        Extracts claim text from generic XML.
        Returns plain text suitable for the Rule Engine.
        """
        try:
            soup = BeautifulSoup(raw_input, "lxml-xml")
        except Exception:
            # Fallback to html parser for malformed XML
            soup = BeautifulSoup(raw_input, "html.parser")

        # Strategy 1: Look for known claim containers
        claim_text_parts = self._extract_by_known_tags(soup)

        # Strategy 2: If nothing found, extract all text
        if not claim_text_parts:
            logger.warning("No claim tags found in generic XML. Extracting all text.")
            claim_text_parts = [soup.get_text(separator="\n")]

        full_text = "\n".join(claim_text_parts).strip()

        if not full_text:
            raise ValueError("Generic XML extraction produced no text.")

        return full_text

    def _extract_by_known_tags(self, soup: BeautifulSoup) -> List[str]:
        """Searches for known claim-related tags and extracts text."""
        parts = []

        for tag_name in self._CLAIM_TAG_NAMES:
            tags = soup.find_all(tag_name)
            for tag in tags:
                text = tag.get_text(separator=" ").strip()
                if text and len(text) > 10:  # Skip trivially short matches
                    parts.append(text)

        return parts
