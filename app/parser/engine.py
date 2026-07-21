"""
Rule-Based Patent Claim Parsing Engine.
Orchestrates claim detection, splitting, dependency resolution,
transition detection, element splitting, and hierarchy reconstruction
to produce a canonical ClaimDocument from normalized text.

This engine handles all non-USPTO-XML inputs:
- Text PDF
- OCR PDF
- TXT
- Copy/Paste
- Generic XML (text extracted)
"""
from typing import List, Dict
from loguru import logger

from app.models.document import ClaimDocument
from app.models.claim import Claim
from app.core.constants import InputType, ClaimType

from app.parser.claim_detector import ClaimStatementDetector
from app.parser.claim_splitter import ClaimSplitter
from app.parser.hierarchy_builder import HierarchyBuilder
from app.parser.confidence_engine import ConfidenceEngine


class ParserEngine:
    """
    Core Rule-Based Patent Claim Parsing Engine.
    Orchestrates the transformation of normalized text into a structured ClaimDocument.
    """

    def __init__(self):
        self.statement_detector = ClaimStatementDetector()
        self.splitter = ClaimSplitter()
        self.hierarchy_builder = HierarchyBuilder()
        self.confidence_engine = ConfidenceEngine()

    def parse(self, normalized_text: str, input_type: InputType) -> ClaimDocument:
        """
        Full rule-based parsing pipeline.
        Returns a ClaimDocument structurally identical to the XML parser output.
        """
        module_scores: Dict[str, float] = {}

        # ── Step 1: Detect claim section header and strip preamble ──
        claims_text = self.statement_detector.detect_and_strip(normalized_text)
        if not claims_text.strip():
            logger.warning("No claim text found after statement detection.")
            return ClaimDocument(
                input_type=input_type,
                claims=[],
                confidence_score=0.0,
            )
        module_scores["claim_detection"] = 100.0
        logger.info("Claim section detected and header stripped.")

        # ── Step 2: Split into individual raw claims ──
        raw_claims = self.splitter.split(claims_text)
        if not raw_claims:
            logger.warning("Claim splitter produced no claims.")
            return ClaimDocument(
                input_type=input_type,
                claims=[],
                confidence_score=0.0,
            )
        logger.info(f"Claim splitter found {len(raw_claims)} claims.")

        # Validate sequential numbering for confidence
        expected = list(range(raw_claims[0].number, raw_claims[0].number + len(raw_claims)))
        actual = [rc.number for rc in raw_claims]
        if actual == expected:
            module_scores["claim_detection"] = 100.0
        else:
            # Non-sequential numbering → lower confidence
            module_scores["claim_detection"] = 85.0
            logger.warning(f"Non-sequential claim numbering detected: {actual}")

        # ── Step 3: Build hierarchy (dependency, transition, elements) ──
        claims: List[Claim] = self.hierarchy_builder.build(raw_claims)
        logger.info(f"Hierarchy builder produced {len(claims)} Claim objects.")

        # ── Step 4: Confidence scoring ──
        # Score dependency detection
        dep_scores = []
        for c in claims:
            if c.claim_type == ClaimType.DEPENDENT and c.parent_claim is not None:
                dep_scores.append(100.0)
            elif c.claim_type == ClaimType.INDEPENDENT and c.parent_claim is None:
                dep_scores.append(100.0)
            else:
                dep_scores.append(80.0)
        module_scores["dependency"] = sum(dep_scores) / len(dep_scores) if dep_scores else 100.0

        # Score transition detection
        trans_scores = []
        for c in claims:
            if c.claim_type == ClaimType.INDEPENDENT:
                trans_scores.append(100.0 if c.header else 70.0)
        module_scores["transition"] = sum(trans_scores) / len(trans_scores) if trans_scores else 100.0

        # Score element detection
        elem_scores = []
        for c in claims:
            if c.elements:
                elem_scores.append(100.0)
            else:
                elem_scores.append(60.0)
        module_scores["enumeration"] = sum(elem_scores) / len(elem_scores) if elem_scores else 100.0
        module_scores["semicolon"] = module_scores["enumeration"]
        module_scores["hierarchy"] = 100.0 if claims else 0.0

        overall = self.confidence_engine.compute(module_scores)
        report = self.confidence_engine.build_report(module_scores)
        logger.info(f"Confidence report: {report}")

        # ── Step 5: Validate ──
        self._validate(claims)

        return ClaimDocument(
            input_type=input_type,
            claims=claims,
            confidence_score=overall,
            metadata={"confidence_report": report},
        )

    @staticmethod
    def _validate(claims: List[Claim]):
        """Validates parsed claims for integrity."""
        if not claims:
            return

        numbers = set()
        for c in claims:
            if c.number in numbers:
                raise ValueError(f"Duplicate claim number detected: {c.number}")
            if c.number <= 0:
                raise ValueError(f"Invalid claim number: {c.number}")
            numbers.add(c.number)

        for c in claims:
            if c.parent_claim is not None and c.parent_claim not in numbers:
                logger.warning(
                    f"Claim {c.number} references non-existent parent claim {c.parent_claim}."
                )

        for c in claims:
            if not c.claim_text or not c.claim_text.strip():
                raise ValueError(f"Claim {c.number} has empty body text.")

