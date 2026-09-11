"""
What kind of claim is this, and what is its amendment status.

Category is decided from the preamble first and the body only as a fallback, because the
preamble is what states the statutory class: "A method of cleaning a surface using the
apparatus of claim 1" is a method claim, even though it says "apparatus".

Order matters.  Jepson and product-by-process are *forms* an apparatus or composition
claim takes, and 112(f) means-plus-function is a construction the whole claim is read
under, so all three are tested before the plain statutory classes -- otherwise every
Jepson claim would simply be reported as an apparatus.
"""
import re
from typing import Optional, Tuple

from app.analysis.hierarchy.models import ClaimCategory, ClaimStatus

# -- status ----------------------------------------------------------------

# An amendment marks each claim: "1. (Currently Amended) A method ...".
_STATUS_BY_TEXT = {
    "original": ClaimStatus.ORIGINAL,
    "previously presented": ClaimStatus.PREVIOUSLY_PRESENTED,
    "previously amended": ClaimStatus.PREVIOUSLY_PRESENTED,
    "currently amended": ClaimStatus.CURRENTLY_AMENDED,
    "current amended": ClaimStatus.CURRENTLY_AMENDED,
    "amended": ClaimStatus.CURRENTLY_AMENDED,
    "new": ClaimStatus.NEW,
    "newly added": ClaimStatus.NEW,
    "cancelled": ClaimStatus.CANCELLED,
    "canceled": ClaimStatus.CANCELLED,
    "withdrawn": ClaimStatus.WITHDRAWN,
    "withdrawn and amended": ClaimStatus.WITHDRAWN_AND_AMENDED,
    "withdrawn - currently amended": ClaimStatus.WITHDRAWN_AND_AMENDED,
    "not entered": ClaimStatus.NOT_ENTERED,
    "no t entered": ClaimStatus.NOT_ENTERED,
}

STATUS_MARKER_PATTERN = re.compile(
    r"^\s*[\(\[]\s*(" + "|".join(sorted((re.escape(k) for k in _STATUS_BY_TEXT), key=len, reverse=True))
    + r")\s*[\)\]]\s*[:.\-]?\s*",
    re.IGNORECASE,
)


def split_status_marker(claim_text: str) -> Tuple[Optional[ClaimStatus], str]:
    """
    Removes a leading "(Currently Amended)" marker and returns it with the remaining text.

    The marker is not part of the claim, and leaving it in place would make it the first
    words of the preamble -- which would then be analysed as claim language and would
    show up in the antecedent and support checks.
    """
    if not claim_text:
        return None, claim_text

    match = STATUS_MARKER_PATTERN.match(claim_text)
    if not match:
        return None, claim_text

    status = _STATUS_BY_TEXT.get(re.sub(r"\s+", " ", match.group(1).strip().lower()))
    return status, claim_text[match.end():].lstrip()


# -- category ---------------------------------------------------------------

# "wherein the improvement comprises", "the improvement comprising" -- 37 CFR 1.75(e).
_JEPSON_PATTERN = re.compile(
    r"\b(?:where(?:in|by)\s+the\s+improvement\s+(?:comprises|comprising)"
    r"|the\s+improvement\s+(?:comprises|comprising)"
    r"|characteri[sz]ed\s+in\s+that"
    r"|characteri[sz]ed\s+by)\b",
    re.IGNORECASE,
)

# A product defined by how it is made: MPEP 2113.
_PRODUCT_BY_PROCESS_PATTERN = re.compile(
    r"\b(?:produced|obtained|obtainable|made|manufactured|prepared|formed)\s+by\s+"
    r"(?:the\s+)?(?:a\s+)?(?:process|method|steps?|the\s+process\s+of\s+claim)\b",
    re.IGNORECASE,
)

# 112(f): a function recited in means/step form.  "means for receiving", "step for X-ing".
_MEANS_PATTERN = re.compile(
    r"\b(?:means|step)\s+for\s+\w+ing\b|\bmeans\s+for\s+\w+\b", re.IGNORECASE
)
# "means" qualified by structure does not invoke 112(f): "fastening means comprising a bolt".
_MEANS_WITH_STRUCTURE = re.compile(
    r"\bmeans\s+for\s+[^,;]{0,80}?\bcompris(?:es|ing)\b", re.IGNORECASE
)

_METHOD_PATTERN = re.compile(
    r"^\s*(?:a|an|the)?\s*[\w\s,\-]{0,60}?\b(method|process)\b", re.IGNORECASE
)
_COMPOSITION_PATTERN = re.compile(
    r"\b(composition|compound|formulation|mixture|alloy|polymer|solution|pharmaceutical\s+composition)\b",
    re.IGNORECASE,
)
_ARTICLE_PATTERN = re.compile(
    r"\b(article\s+of\s+manufacture|article|computer[\s-]*readable\s+(?:storage\s+)?(?:medium|media)"
    r"|non-transitory|program\s+product|kit|storage\s+medium|manufacture)\b",
    re.IGNORECASE,
)
_APPARATUS_PATTERN = re.compile(
    r"\b(apparatus|device|system|machine|assembly|circuit|module|engine|vehicle|robot"
    r"|processor|controller|server|tool|instrument|appliance|structure|unit)\b",
    re.IGNORECASE,
)
# A method claim's body recites acts; useful when the preamble names no class at all.
_STEP_BODY_PATTERN = re.compile(
    r"(?:^|[;:\n])\s*(?:the\s+steps?\s+of\s+)?\w+ing\b", re.IGNORECASE
)


def classify(preamble: str, full_text: str = "") -> ClaimCategory:
    """
    The statutory category of a claim.

    ``preamble`` is the claim's own preamble; ``full_text`` is the whole claim, used for
    the forms that are only visible in the body (means-plus-function limitations sit in
    the body, not the preamble).
    """
    preamble = (preamble or "").strip()
    body = full_text or preamble

    if _JEPSON_PATTERN.search(body):
        return ClaimCategory.JEPSON

    if _PRODUCT_BY_PROCESS_PATTERN.search(body) and not _is_method(preamble, body):
        return ClaimCategory.PRODUCT_BY_PROCESS

    if _MEANS_PATTERN.search(body) and not _MEANS_WITH_STRUCTURE.search(body):
        return ClaimCategory.MEANS_PLUS_FUNCTION

    if _is_method(preamble, body):
        return ClaimCategory.METHOD

    # The statutory class is the thing being claimed, not everything the preamble
    # mentions.  "A base assembly of a cleaning appliance to extract a waste solution"
    # claims an assembly; matching the whole preamble made it a composition, because it
    # contains the word "solution".
    head = _claimed_subject(preamble)
    if _COMPOSITION_PATTERN.search(head):
        return ClaimCategory.COMPOSITION
    if _ARTICLE_PATTERN.search(head):
        return ClaimCategory.ARTICLE
    if _APPARATUS_PATTERN.search(head):
        return ClaimCategory.APPARATUS

    # The subject names no class; widen to the rest of the preamble, then to the claim.
    wider = _classifiable_head(preamble)
    if _APPARATUS_PATTERN.search(wider):
        return ClaimCategory.APPARATUS
    if _ARTICLE_PATTERN.search(wider):
        return ClaimCategory.ARTICLE
    if _COMPOSITION_PATTERN.search(wider):
        return ClaimCategory.COMPOSITION

    if _COMPOSITION_PATTERN.search(body):
        return ClaimCategory.COMPOSITION
    if _ARTICLE_PATTERN.search(body):
        return ClaimCategory.ARTICLE
    if _APPARATUS_PATTERN.search(body):
        return ClaimCategory.APPARATUS

    return ClaimCategory.UNKNOWN


def _is_method(preamble: str, body: str) -> bool:
    head = _claimed_subject(preamble)
    if _METHOD_PATTERN.match(head):
        return True
    # "A method of ..." can be buried after a status marker or a dependency phrase.
    if re.search(r"\b(?:a|the)\s+(?:computer[- ]implemented\s+)?(method|process)\b", head, re.I):
        return True
    if not head and _STEP_BODY_PATTERN.search(body):
        return True
    return False


# Where the claimed subject ends and its context begins.  "A base assembly | of a
# cleaning appliance", "A method | for recovering a table structure".
_SUBJECT_END = re.compile(
    r"\s+(?:of|for|to|in|on|with|from|at|by|that|which|wherein|configured|adapted|operable"
    r"|comprising|comprises|consisting|consists|including|includes|having|has|containing"
    r"|contains|used|usable|suitable)\b|[,;:(]",
    re.IGNORECASE,
)


def _claimed_subject(preamble: str) -> str:
    """
    The noun phrase the claim is *to*, which is what fixes its statutory class.

    Everything after the first preposition or transition describes the environment the
    subject sits in, and those words routinely name other statutory classes -- a device
    "to extract a waste solution", a method "of using the composition of claim 1".
    """
    head = _classifiable_head(preamble)
    if not head:
        return ""

    match = _SUBJECT_END.search(head)
    subject = head[:match.start()].strip() if match else head.strip()

    # "An article of manufacture" and "A composition of matter" lose their meaning when
    # cut at "of"; keep the fuller phrase when the cut leaves only an article and a noun
    # that the longer form qualifies.
    if match and re.fullmatch(r"(?:an?|the)\s+(?:article|composition)", subject, re.IGNORECASE):
        return head.strip()

    return subject or head.strip()


def _classifiable_head(preamble: str) -> str:
    """
    The part of the preamble that names the claim's own class.

    A dependent claim's preamble repeats its parent's class first -- "The method of claim 1"
    -- so the text up to the claim reference is what classifies it.  Anything after
    "of claim N" describes the parent, not this claim.
    """
    if not preamble:
        return ""
    cut = re.split(r"\b(?:of|in|according\s+to|as\s+(?:recited|defined|set\s+forth)\s+in)\s+claim\s+\d+",
                   preamble, maxsplit=1, flags=re.IGNORECASE)[0]
    return cut.strip() or preamble.strip()
