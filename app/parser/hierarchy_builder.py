"""
Hierarchy Builder.
Constructs the final ClaimElement tree from parsed components.
Converts semicolon elements and enumeration items into nested ClaimElement objects
matching the canonical model used by the XML parser.
"""
import re
from typing import List, Optional, Tuple
from app.models.claim import Claim, ClaimElement
from app.core.constants import ClaimType, ElementType
from app.parser.claim_splitter import RawClaim
from app.parser.dependency_detector import DependencyDetector, DependencyResult
from app.parser.transition_detector import TransitionDetector, TransitionResult
from app.parser.semicolon_parser import SemicolonParser
from app.parser.enumeration_detector import EnumerationDetector


class HierarchyBuilder:
    """
    Builds the final Claim objects with nested ClaimElement trees.
    This is the central assembly point for the rule-based parser.
    """

    def __init__(self):
        self.dependency_detector = DependencyDetector()
        self.transition_detector = TransitionDetector()
        self.semicolon_parser = SemicolonParser()
        self.enumeration_detector = EnumerationDetector()

    def build(self, raw_claims: List[RawClaim]) -> List[Claim]:
        """
        Converts a list of RawClaim objects into fully populated Claim objects.

        Claims marked "(Canceled)" are split off rather than returned: their text is no
        longer part of the application, so analysing it would report defects in claims
        that do not exist.  They are reported by :meth:`build_with_cancelled` so the
        report can still list them.
        """
        claims, _cancelled = self.build_with_cancelled(raw_claims)
        return claims

    def build_with_cancelled(
        self, raw_claims: List[RawClaim]
    ) -> Tuple[List[Claim], List[int]]:
        """Returns the live claims, and the numbers of the claims marked cancelled."""
        claims: List[Claim] = []
        cancelled: List[int] = []

        for rc in raw_claims:
            if rc.deleted:
                cancelled.append(rc.number)
                continue
            claims.append(self._build_single_claim(rc))

        return claims, cancelled

    def _build_single_claim(self, raw: RawClaim) -> Claim:
        """Builds a single Claim from a RawClaim."""
        full_text = raw.text

        # 1. Dependency detection
        dep: DependencyResult = self.dependency_detector.detect(full_text)
        claim_type = ClaimType.INDEPENDENT if dep.is_independent else ClaimType.DEPENDENT
        parent_claim = dep.parent_claims[0] if dep.parent_claims else None

        # 2. Transition detection (preamble / transition / body)
        trans: TransitionResult = self.transition_detector.detect(full_text)

        prospective_header = ""
        if trans.preamble:
            prospective_header += trans.preamble
        if trans.transition:
            prospective_header += f" {trans.transition}"
            if trans.has_colon:
                prospective_header += ":"
            
        prospective_header = prospective_header.strip()
        body = trans.body

        has_colon = trans.has_colon or ":" in body
        has_semicolons = self.semicolon_parser.has_semicolons(body)
        has_enumerations = self.enumeration_detector.has_enumerations(body)

        if prospective_header and (has_colon or has_semicolons or has_enumerations):
            header = prospective_header
        else:
            full_body = (prospective_header + " " + body).strip() if prospective_header else body

            if ":" in full_body:
                # Split at the first colon
                parts = full_body.split(":", 1)
                header = parts[0].strip() + ":"
                body = parts[1].strip()
            elif not self.semicolon_parser.has_semicolons(full_body) and not self.enumeration_detector.has_enumerations(full_body):
                # No structural markers, promote entire body to header (matches XML behavior for simple claims)
                header = full_body
                body = ""
            elif not self.semicolon_parser.has_semicolons(full_body) and self.enumeration_detector.has_enumerations(full_body):
                # Enumerations but no semicolons. Extract text before first enumeration.
                first_enum = self.enumeration_detector.detect_inline(full_body)
                if first_enum:
                    idx = full_body.find(first_enum[0].marker)
                    if idx > 0:
                        header = full_body[:idx].strip()
                        body = full_body[idx:].strip()
                else:
                    header = full_body
                    body = ""
            else:
                header = ""
                body = full_body

        # 3. Build elements from the remaining body
        elements = self._build_elements(body)

        metadata = {
            "claim_category": trans.category,
        }
        if dep.parent_claims:
            metadata["parent_claims"] = dep.parent_claims
        if raw.rendered_number is not None:
            # The source showed a second number beside this one ("12.[13.]"); kept so
            # the report can explain a number the reader may see in the document.
            metadata["rendered_number"] = raw.rendered_number

        return Claim(
            number=raw.number,
            claim_type=claim_type,
            parent_claim=parent_claim,
            claim_text=full_text,
            header=header,
            elements=elements,
            metadata=metadata,
        )

    def _build_elements(self, body: str) -> List[ClaimElement]:
        """
        Builds a list of ClaimElements from the claim body.
        Priority: enumerations > semicolons > single body element.
        """
        if not body or not body.strip():
            return []

        # Check for inline enumerations first: (a) ... (b) ... (c) ...
        if self.enumeration_detector.has_enumerations(body):
            enum_items = self.enumeration_detector.detect_inline(body)
            if enum_items:
                elements = []
                for i, item in enumerate(enum_items):
                    el_type = ElementType.ENUMERATION
                    el = ClaimElement(
                        text=item.text,
                        level=item.level + 1,
                        marker=item.marker,
                        element_type=el_type,
                        order=i,
                    )
                    elements.append(el)
                return elements

        # Check for semicolon-delimited elements
        if self.semicolon_parser.has_semicolons(body):
            sem_items = self.semicolon_parser.parse(body)
            if len(sem_items) > 1:
                elements = []
                current_level = 1
                for item in sem_items:
                    # Detect if this element itself has sub-enumerations
                    children = []
                    if self.enumeration_detector.has_enumerations(item.text):
                        sub_items = self.enumeration_detector.detect_inline(item.text)
                        for j, sub in enumerate(sub_items):
                            child = ClaimElement(
                                text=sub.text,
                                level=current_level + 1,
                                marker=sub.marker,
                                element_type=ElementType.ENUMERATION,
                                order=j,
                            )
                            children.append(child)

                    el_type = ElementType.BODY_ELEMENT
                    # Detect wherein clauses
                    if item.text.lower().startswith("wherein"):
                        el_type = ElementType.WHEREIN_CLAUSE
                        # A wherein clause qualifies the claim as a whole, so it
                        # closes any sub-list opened by an earlier colon instead
                        # of inheriting its depth.  Without this reset every
                        # colon pushed the rest of the claim one level deeper,
                        # so late elements drifted far to the right.
                        current_level = 1

                    text_for_element = item.text
                    if children:
                        # Strip the enumeration markers from the parent text
                        # since they've been promoted to children
                        first_enum = self.enumeration_detector.detect_inline(item.text)
                        if first_enum:
                            idx = item.text.find(first_enum[0].marker)
                            if idx > 0:
                                text_for_element = item.text[:idx].strip()
                            else:
                                text_for_element = item.text

                    colon_match = re.search(r':(\s+|$)', text_for_element)
                    if colon_match:
                        colon_idx = colon_match.start()
                        parent_text = text_for_element[:colon_idx + 1].strip()
                        child_text = text_for_element[colon_idx + 1:].strip()

                        el_parent = ClaimElement(
                            text=parent_text,
                            level=current_level,
                            marker=None,
                            element_type=el_type,
                            order=item.order,
                            children=[],
                        )
                        elements.append(el_parent)

                        # Nest what follows under the colon, but never past the
                        # third level -- deeper indents only push the text off
                        # the right margin.
                        current_level = min(current_level + 1, 3)


                        if child_text:
                            el_child = ClaimElement(
                                text=child_text,
                                level=current_level,
                                marker=None,
                                element_type=ElementType.BODY_ELEMENT,
                                order=item.order,
                                children=children,
                            )
                            elements.append(el_child)
                    else:
                        el = ClaimElement(
                            text=text_for_element,
                            level=current_level,
                            marker=None,
                            element_type=el_type,
                            order=item.order,
                            children=children,
                        )
                        elements.append(el)
                return elements

        # Fallback: single body element
        el_type = ElementType.BODY_ELEMENT
        if body.strip().lower().startswith("wherein"):
            el_type = ElementType.WHEREIN_CLAUSE

        return [
            ClaimElement(
                text=body.strip(),
                level=1,
                marker=None,
                element_type=el_type,
                order=0,
            )
        ]

    @staticmethod
    def _format_element(el: ClaimElement, indent: int = 1) -> str:
        """Formats a ClaimElement into indented text."""
        prefix = "    " * indent
        line = f"{prefix}{el.text}"
        child_lines = [
            HierarchyBuilder._format_element(child, indent + 1)
            for child in el.children
        ]
        if child_lines:
            return line + "\n" + "\n".join(child_lines)
        return line
