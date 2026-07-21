import re
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup, Tag, NavigableString
from app.models.claim import Claim, ClaimElement
from app.core.constants import ClaimType, ElementType

class USPTOXMLExtractor:
    """
    Production implementation of the USPTO XML Extractor.
    Extracts the claim hierarchy deterministically from USPTO XML files.
    """
    def __init__(self):
        # Patterns for metadata extraction
        self.transition_pattern = re.compile(
            r'\b(comprising|consisting of|consisting essentially of|including|having|containing)\b',
            re.IGNORECASE
        )
        self.claim_ref_pattern = re.compile(r'claim\s+(\d+)', re.IGNORECASE)

    def extract(self, raw_input: bytes) -> List[Claim]:
        """
        Parses USPTO XML and returns a list of fully populated Claim objects.
        """
        # Parse XML using lxml backend for speed and robustness
        soup = BeautifulSoup(raw_input, "lxml-xml")
        
        claims_tag = soup.find("claims")
        if not claims_tag:
            raise ValueError("Invalid XML: Missing <claims> section.")
            
        claim_tags = claims_tag.find_all("claim", recursive=False)
        
        parsed_claims = []
        for claim_tag in claim_tags:
            parsed_claims.append(self._parse_single_claim(claim_tag))
            
        self._validate_claims(parsed_claims)
            
        return parsed_claims

    def _validate_claims(self, claims: List[Claim]):
        if not claims:
            return
            
        claim_numbers = set()
        for c in claims:
            if c.number in claim_numbers:
                raise ValueError(f"Duplicate claim number detected: {c.number}")
            if c.number <= 0:
                raise ValueError("Missing or invalid claim number.")
            claim_numbers.add(c.number)
            
        for c in claims:
            if c.parent_claim is not None:
                if c.parent_claim not in claim_numbers:
                    raise ValueError(f"Broken reference in claim {c.number}: Parent claim {c.parent_claim} does not exist.")

    def _parse_single_claim(self, claim_tag: Tag) -> Claim:
        # Extract claim number
        claim_id = claim_tag.get("id", "")
        num_match = re.search(r'\d+', claim_id)
        claim_number = int(num_match.group()) if num_match else 0
        
        # Determine dependency
        claim_ref_tag = claim_tag.find("claim-ref")
        parent_claim = None
        if claim_ref_tag:
            ref_text = claim_ref_tag.get_text()
            ref_match = self.claim_ref_pattern.search(ref_text)
            if ref_match:
                parent_claim = int(ref_match.group(1))
                
        is_independent = parent_claim is None
        claim_type = ClaimType.INDEPENDENT if is_independent else ClaimType.DEPENDENT
        
        # Parse hierarchy (claim-text elements)
        root_claim_texts = claim_tag.find_all("claim-text", recursive=False)
        
        elements = []
        header = ""
        
        if root_claim_texts:
            first_ct = root_claim_texts[0]
            header = self._extract_immediate_text(first_ct)
            # Remove the claim number (e.g. "<b>1</b>. " or "1. ") from the header
            header = re.sub(r'^(?:<b[^>]*>)?\s*\d+\s*(?:</b>)?\.\s*', '', header).strip()
            
            # Parse children of the first claim-text as level 1 elements
            # USPTO typically nests elements inside the first claim-text
            child_cts = first_ct.find_all("claim-text", recursive=False)
            for ct in child_cts:
                elements.extend(self._parse_claim_text(ct, level=1))
                
            # Parse any subsequent root claim-texts (sometimes happens)
            for ct in root_claim_texts[1:]:
                elements.extend(self._parse_claim_text(ct, level=1))
                
        metadata = {
            "claim_category": self._detect_category(header),
            "raw_xml": str(claim_tag)
        }
            
        return Claim(
            number=claim_number,
            claim_type=claim_type,
            parent_claim=parent_claim,
            header=header,
            elements=elements,
            metadata=metadata
        )

    def _extract_immediate_text(self, claim_text_tag: Tag) -> str:
        """Extracts text preserving internal formatting but excluding nested claim-text tags."""
        parts = []
        allowed_tags = {"b", "i", "u", "sub", "sup"}
        
        for child in claim_text_tag.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name == "claim-text":
                    continue
                
                if child.name in allowed_tags:
                    # Keep valid formatting tags like <b>, <i>, <sub>, <sup>
                    parts.append(str(child))
                else:
                    # Replace tags like <claim-ref> with their inner text
                    parts.append(child.get_text())
        
        text = "".join(parts).strip()
        return re.sub(r'\s+', ' ', text)

    def _parse_claim_text(self, claim_text_tag: Tag, level: int) -> List[ClaimElement]:
        immediate_text = self._extract_immediate_text(claim_text_tag)
        
        element_type = ElementType.BODY_ELEMENT
        marker = None
        
        # Detect markers like (a), (i), etc.
        marker_match = re.match(r'^\s*(\([a-zA-Z0-9]+\))', immediate_text)
        if marker_match:
            marker = marker_match.group(1)
            element_type = ElementType.ENUMERATION
            
        if "wherein" in immediate_text.lower():
            element_type = ElementType.WHEREIN_CLAUSE
            
        el = ClaimElement(
            text=immediate_text,
            level=level,
            marker=marker,
            element_type=element_type
        )
        
        # Process children
        child_cts = claim_text_tag.find_all("claim-text", recursive=False)
        for child_ct in child_cts:
            el.children.extend(self._parse_claim_text(child_ct, level + 1))
            
        return [el]

    def _detect_category(self, text: str) -> str:
        text_lower = text.lower()
        if "method" in text_lower or "process" in text_lower:
            return "method"
        if "system" in text_lower:
            return "system"
        if "apparatus" in text_lower or "device" in text_lower or "machine" in text_lower:
            return "apparatus"
        if "composition" in text_lower:
            return "composition"
        if "medium" in text_lower:
            return "computer-readable medium"
        return "unknown"
