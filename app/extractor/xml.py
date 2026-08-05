from typing import List, Optional, Tuple, Dict, Any
import re
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

    def extract(self, raw_input: bytes) -> Tuple[List[Claim], Dict[str, Any]]:
        """
        Parses USPTO XML and returns a tuple of fully populated Claim objects and document metadata.
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
            
        metadata = self._extract_document_metadata(soup)
            
        return parsed_claims, metadata

    def _extract_document_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extracts bibliographic metadata from the XML document."""
        metadata = {
            "title": None,
            "application_number": None,
            "application_date": None,
            "publication_number": None,
            "publication_date": None,
            "patent_number": None,
            "kind_code": None,
            "country": None,
            "language": None
        }

        def format_date(raw_date: str) -> str:
            if raw_date and len(raw_date) == 8 and raw_date.isdigit():
                return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            return raw_date

        # Title
        title_tag = soup.find("invention-title")
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)

        # 1. Document Type & Language & Status
        root_tag = soup.find(re.compile(r'us-patent-(grant|application)'))
        if root_tag:
            metadata["language"] = root_tag.get("lang", "en").lower()
            metadata["country"] = root_tag.get("country", "US")

        # 2. Application No & Date
        app_ref = soup.find("application-reference")
        if app_ref:
            doc_id = app_ref.find("document-id")
            if doc_id:
                doc_number = doc_id.find("doc-number")
                if doc_number:
                    metadata["application_number"] = doc_number.get_text(strip=True)
                date = doc_id.find("date")
                if date:
                    metadata["application_date"] = format_date(date.get_text(strip=True))
                if not metadata["country"]:
                    country_tag = doc_id.find("country")
                    if country_tag:
                        metadata["country"] = country_tag.get_text(strip=True)

        # 3. Publication No & Date, Kind Code
        pub_ref = soup.find("publication-reference")
        if pub_ref:
            doc_id = pub_ref.find("document-id")
            if doc_id:
                doc_number = doc_id.find("doc-number")
                if doc_number:
                    metadata["publication_number"] = doc_number.get_text(strip=True)
                    if root_tag and "grant" in root_tag.name:
                        metadata["patent_number"] = metadata["publication_number"]
                date = doc_id.find("date")
                if date:
                    metadata["publication_date"] = format_date(date.get_text(strip=True))
                kind = doc_id.find("kind")
                if kind:
                    metadata["kind_code"] = kind.get_text(strip=True)
                if not metadata["country"]:
                    country_tag = doc_id.find("country")
                    if country_tag:
                        metadata["country"] = country_tag.get_text(strip=True)
                    
        if not metadata["patent_number"] and metadata["publication_number"]:
            metadata["patent_number"] = metadata["publication_number"]

        return metadata
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
        
        # Determine dependency and all references
        parent_claim = None
        references = []
        
        all_claim_refs = claim_tag.find_all("claim-ref")
        for ref_tag in all_claim_refs:
            ref_text = ref_tag.get_text(strip=True)
            idref = ref_tag.get("idref", "")
            ref_match = self.claim_ref_pattern.search(ref_text)
            ref_num = int(ref_match.group(1)) if ref_match else None
            
            if ref_num is not None:
                # The first valid reference is typically the parent claim
                if parent_claim is None:
                    parent_claim = ref_num
                
                references.append({
                    "text": ref_text,
                    "claim_number": ref_num,
                    "idref": idref
                })
                
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
            references=references,
            header=header,
            elements=elements,
            metadata=metadata
        )

    def _extract_immediate_text(self, claim_text_tag: Tag) -> str:
        """Extracts text preserving internal formatting but excluding nested claim-text tags."""
        allowed_tags = {"b", "i", "u", "sub", "sup"}
        
        def _process_node(node) -> str:
            if isinstance(node, NavigableString):
                return str(node)
            elif isinstance(node, Tag):
                if node.name == "claim-text":
                    return ""
                
                inner_text = "".join(_process_node(child) for child in node.children)
                
                if node.name in allowed_tags:
                    return f"<{node.name}>{inner_text}</{node.name}>"
                else:
                    return inner_text
            return ""

        parts = []
        for child in claim_text_tag.children:
            if isinstance(child, Tag) and child.name == "claim-text":
                continue
            parts.append(_process_node(child))
            
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
