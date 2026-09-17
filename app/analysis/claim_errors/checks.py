"""
The individual checks behind section II.

Each check is a function over one claim (or over the whole set) that yields
:class:`ClaimIssue` objects.  They are separate functions rather than one pass so a check
can be read, tested and argued with on its own -- which matters here, because several of
them are judgement calls an attorney may disagree with, and the report has to say exactly
which rule it is applying.

Everything that points at words in the claim reports offsets into the *block* text from
:func:`iter_claim_blocks`, so section II findings can be highlighted by the same renderer
as the antecedent findings.
"""
import re
from typing import Dict, Iterator, List, Optional, Set

from app.analysis.antecedent.claim_walker import iter_claim_blocks
from app.analysis.claim_errors.models import ClaimIssue, ClaimIssueType
from app.analysis.hierarchy.classifier import split_status_marker
from app.analysis.hierarchy.models import ClaimStatus
from app.analysis.models import FindingLocation, Severity
from app.core.constants import ClaimType
from app.models.claim import Claim
from app.models.document import ClaimDocument

# Fee thresholds: 37 CFR 1.16(h) and (i).
FREE_CLAIMS = 20
FREE_INDEPENDENT_CLAIMS = 3

# An independent claim needs a true transitional phrase, which is what sets the claim's
# open or closed scope (MPEP 2111.03).
_TRANSITION_PATTERN = re.compile(
    r"\b(comprising|comprises|consisting\s+essentially\s+of|consisting\s+of|consists\s+of"
    r"|including|includes|having|has|containing|contains|characteri[sz]ed\s+in\s+that)\b",
    re.IGNORECASE,
)

# A dependent claim normally adds its limitation with "wherein" and needs no transition of
# its own -- it inherits the parent's.  Flagging those was reporting every ordinary
# dependent claim in the set.
_DEPENDENT_CONNECTOR_PATTERN = re.compile(
    r"\b(wherein|whereby|in\s+which|further\s+comprising|further\s+including"
    r"|configured\s+to|adapted\s+to|operable\s+to|and\s+wherein)\b",
    re.IGNORECASE,
)

# Terms of degree: definite only when the specification supplies a standard for measuring
# them (MPEP 2173.05(b)).  Reported so the drafter confirms that standard exists.
_INDEFINITE_TERMS = [
    "substantially", "approximately", "about", "relatively", "generally", "essentially",
    "significantly", "sufficiently", "suitable", "suitably", "adequate", "appropriate",
    "near", "close to", "similar to", "like", "type", "kind of", "somewhat", "very",
    "high", "low", "large", "small", "thin", "thick", "strong", "weak", "fast", "slow",
]
# The short adjectives above are only vague on their own; qualified they are fine
# ("high-pressure valve"), so they are matched as standalone words only.
_INDEFINITE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in _INDEFINITE_TERMS) + r")\b",
    re.IGNORECASE,
)
# These read as ordinary technical vocabulary in these fixed phrases.
_INDEFINITE_EXCEPTIONS = re.compile(
    r"\b(?:high|low)[- ](?:pass|level|density|frequency|voltage|pressure|speed|resolution)\b"
    r"|\btype\s+\d|\bdata\s+type\b|\blike\s+manner\b",
    re.IGNORECASE,
)

_OPTIONAL_PATTERN = re.compile(
    r"\b(optionally|preferably|desirably|advantageously|if\s+desired|as\s+needed"
    r"|may\s+(?:be|include|comprise|have)|can\s+(?:be|include|comprise|have)"
    r"|could\s+be|should\s+be)\b",
    re.IGNORECASE,
)

# "and/or" is not here: it is an accepted way to recite alternatives, not an example,
# and flagging it reported a defect in every claim that used it.
_EXEMPLARY_PATTERN = re.compile(
    r"\b(for\s+example|e\.g\.|such\s+as|including\s+but\s+not\s+limited\s+to"
    r"|for\s+instance|i\.e\.|et\s+cetera|etc\.)",
    re.IGNORECASE,
)

_TRADEMARK_PATTERN = re.compile(r"[™®]|\b(?:TM|\(R\))\b")

# A bare number in claim text is a reference numeral only when it is not a quantity,
# a units value, or a claim cross-reference.
_REFERENCE_NUMERAL_PATTERN = re.compile(r"(?<![\(\w.\-/])\b(\d{2,4})\b(?![\)\w%.\-/])")
_NUMERAL_CONTEXT_EXCEPTION = re.compile(
    r"\b(?:claim|claims|figure|fig\.?|page|line|about|least|most|than|between|and)\s*$",
    re.IGNORECASE,
)

# "claims 1 and 2" is improper; a multiple dependent claim must be in the alternative.
_MULTIPLE_AND_PATTERN = re.compile(
    r"\bclaims?\s+\d+\s*(?:,\s*\d+\s*)*(?:and)\s+\d+", re.IGNORECASE
)


def _blocks(claim: Claim):
    return list(iter_claim_blocks(claim))


def _location(block, start: int, end: int) -> FindingLocation:
    return FindingLocation(
        element_index=block.index,
        element_text=block.text,
        char_start=start,
        char_end=end,
        source=block.source,
    )


def _issue(
    issue_type: ClaimIssueType,
    claim_number: Optional[int],
    message: str,
    severity: Severity = Severity.WARNING,
    suggestion: Optional[str] = None,
    term: str = "",
    locations: Optional[List[FindingLocation]] = None,
) -> ClaimIssue:
    locations = locations or []
    return ClaimIssue(
        type=issue_type,
        severity=severity,
        claim_number=claim_number,
        message=message,
        suggestion=suggestion,
        term=term,
        location=locations[0] if locations else None,
        locations=locations,
    )


# -- dependency -------------------------------------------------------------


def check_dependencies(
    claim: Claim, numbers: Set[int], cancelled: Set[int], multiple_dependents: Set[int]
) -> Iterator[ClaimIssue]:
    """Validates a claim's parent references against 37 CFR 1.75(c) and 112(e)."""
    parents = _parents(claim)
    if not parents:
        return

    for parent in parents:
        if parent == claim.number:
            yield _issue(
                ClaimIssueType.SELF_DEPENDENT, claim.number,
                f"Claim {claim.number} refers to itself.",
                Severity.ERROR,
                suggestion=(
                    "Point the dependency at the claim this one is meant to further "
                    "limit. A claim renumbered by an amendment often keeps the "
                    "cross-reference it had under the old numbering."
                ),
            )
        elif parent in cancelled:
            yield _issue(
                ClaimIssueType.DEPENDS_ON_CANCELLED, claim.number,
                f"Claim {claim.number} depends on claim {parent}, which has been cancelled.",
                Severity.ERROR,
                suggestion=f"Redirect claim {claim.number} to a pending claim.",
            )
        elif parent not in numbers:
            yield _issue(
                ClaimIssueType.MISSING_PARENT, claim.number,
                f"Claim {claim.number} depends on claim {parent}, which does not exist.",
                Severity.ERROR,
                suggestion=f"Correct the reference in claim {claim.number}.",
            )
        elif parent > claim.number:
            yield _issue(
                ClaimIssueType.FORWARD_DEPENDENCY, claim.number,
                f"Claim {claim.number} depends on claim {parent}, which follows it. "
                f"A dependent claim may refer only to a preceding claim.",
                Severity.ERROR,
                suggestion="Renumber the claims so the parent precedes the dependent claim.",
            )

    if len(parents) > 1:
        improper = sorted(p for p in parents if p in multiple_dependents)
        if improper:
            yield _issue(
                ClaimIssueType.IMPROPER_MULTIPLE_DEPENDENT, claim.number,
                f"Claim {claim.number} is a multiple dependent claim that refers to "
                f"claim {', '.join(str(p) for p in improper)}, which is itself a multiple "
                f"dependent claim.",
                Severity.ERROR,
                suggestion=(
                    "A multiple dependent claim may not serve as a basis for another "
                    "multiple dependent claim (35 U.S.C. 112(e))."
                ),
            )

        if _MULTIPLE_AND_PATTERN.search(claim.claim_text or ""):
            match = _MULTIPLE_AND_PATTERN.search(claim.claim_text or "")
            yield _issue(
                ClaimIssueType.MULTIPLE_DEPENDENT_CONJUNCTION, claim.number,
                f'Claim {claim.number} refers to more than one claim conjunctively '
                f'("{match.group(0)}").',
                Severity.ERROR,
                term=match.group(0),
                suggestion='A multiple dependent claim must be in the alternative: use "or".',
            )


def _parents(claim: Claim) -> List[int]:
    if claim.metadata and claim.metadata.get("parent_claims"):
        return sorted({int(p) for p in claim.metadata["parent_claims"]})
    if claim.parent_claim is not None:
        return [int(claim.parent_claim)]
    return []


# -- claim set --------------------------------------------------------------


def check_claim_set(document: ClaimDocument) -> Iterator[ClaimIssue]:
    """Checks that hold over the claim set rather than any one claim."""
    claims = document.claims
    if not claims:
        return

    numbers = [c.number for c in claims]

    seen: Dict[int, int] = {}
    for number in numbers:
        seen[number] = seen.get(number, 0) + 1
    for number, count in sorted(seen.items()):
        if count > 1:
            yield _issue(
                ClaimIssueType.DUPLICATE_CLAIM_NUMBER, number,
                f"Claim number {number} is used {count} times.",
                Severity.ERROR,
                suggestion="Renumber the claims consecutively.",
            )

    # A cancelled claim keeps its number, so its number is not a gap in the sequence.
    cancelled = {int(n) for n in (document.metadata or {}).get("cancelled_claims", [])}
    ordered = sorted(set(numbers) | cancelled)
    expected = list(range(ordered[0], ordered[0] + len(ordered)))
    if ordered != expected:
        missing = sorted(set(expected) - set(ordered))
        detail = f" Missing: {', '.join(str(m) for m in missing)}." if missing else ""
        yield _issue(
            ClaimIssueType.NON_SEQUENTIAL_NUMBERING, None,
            f"Claims are numbered {_summarise(ordered)} rather than consecutively "
            f"from {ordered[0]}.{detail}",
            Severity.WARNING,
            suggestion="Number the claims consecutively in Arabic numerals (37 CFR 1.126).",
        )

    if not any(c.claim_type == ClaimType.INDEPENDENT for c in claims):
        yield _issue(
            ClaimIssueType.NO_INDEPENDENT_CLAIM, None,
            "No independent claim was found: every claim refers to another claim.",
            Severity.ERROR,
            suggestion="Check that the first claim does not carry a stray claim reference.",
        )

    total = len(claims)
    if total > FREE_CLAIMS:
        yield _issue(
            ClaimIssueType.EXCESS_CLAIMS, None,
            f"The application contains {total} claims; excess claims fees apply above "
            f"{FREE_CLAIMS}.",
            Severity.WARNING,
        )

    independent = [c for c in claims if c.claim_type == ClaimType.INDEPENDENT]
    if len(independent) > FREE_INDEPENDENT_CLAIMS:
        yield _issue(
            ClaimIssueType.EXCESS_INDEPENDENT_CLAIMS, None,
            f"The application contains {len(independent)} independent claims "
            f"({', '.join(str(c.number) for c in independent)}); excess independent claim "
            f"fees apply above {FREE_INDEPENDENT_CLAIMS}.",
            Severity.WARNING,
        )


def _summarise(numbers: List[int]) -> str:
    """"1-11, 13, 15-18" -- compact enough for a one-line message."""
    if not numbers:
        return ""
    runs, start, previous = [], numbers[0], numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        runs.append((start, previous))
        start = previous = number
    runs.append((start, previous))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


# -- form -------------------------------------------------------------------


def check_form(claim: Claim) -> Iterator[ClaimIssue]:
    """Punctuation, capitalisation and the transitional phrase."""
    text = (claim.claim_text or "").strip()
    if not text:
        return

    is_dependent = bool(_parents(claim))
    has_transition = bool(_TRANSITION_PATTERN.search(text))
    if is_dependent:
        has_transition = has_transition or bool(_DEPENDENT_CONNECTOR_PATTERN.search(text))

    if not has_transition:
        yield _issue(
            ClaimIssueType.MISSING_TRANSITION, claim.number,
            f"Claim {claim.number} has no transitional phrase.",
            Severity.WARNING,
            suggestion=(
                'Separate the preamble from the body with a transition such as '
                '"comprising", "consisting of" or "including"'
                + ('; a dependent claim may add its limitation with "wherein".'
                   if is_dependent else '.')
            ),
        )

    if not text.endswith("."):
        yield _issue(
            ClaimIssueType.NO_TERMINAL_PERIOD, claim.number,
            f"Claim {claim.number} does not end with a period.",
            Severity.WARNING,
            suggestion="Each claim must end with a single period.",
        )

    # One sentence per claim: a period anywhere but the end splits the claim in two.
    # Abbreviations and decimals are not sentence ends.
    body = text[:-1] if text.endswith(".") else text
    internal = [
        match for match in re.finditer(r"\.(?=\s+[A-Z])", body)
        if not _is_abbreviation(body, match.start())
    ]
    if internal:
        yield _issue(
            ClaimIssueType.INTERNAL_PERIOD, claim.number,
            f"Claim {claim.number} contains {len(internal)} sentence break(s); a claim "
            f"must be a single sentence.",
            Severity.WARNING,
            suggestion="Replace the internal period with a semicolon or a comma.",
        )

    first = re.sub(r"^[\(\[][^\)\]]*[\)\]]\s*", "", text)
    if first[:1].islower():
        yield _issue(
            ClaimIssueType.LOWERCASE_START, claim.number,
            f"Claim {claim.number} does not start with a capital letter.",
            Severity.WARNING,
        )


def _is_abbreviation(text: str, period_index: int) -> bool:
    """True for "e.g.", "U.S.", "FIG." and single initials -- not sentence ends."""
    window = text[max(0, period_index - 6):period_index + 1]
    if re.search(r"\b(?:e\.g|i\.e|U\.S|No|Fig|FIG|et\s+al|cf|vs|Dr|Mr|Ms)\.$", window):
        return True
    # A single letter before the period: "A. B." style initials.
    return bool(re.search(r"(?:^|[\s(])[A-Za-z]\.$", window))


# -- definiteness -----------------------------------------------------------


def check_language(claim: Claim) -> Iterator[ClaimIssue]:
    """
    Words that make a claim's scope arguable.

    These are warnings, never errors: a term of degree is definite when the specification
    gives a standard for measuring it, which this check cannot know.  The report's job is
    to put the term in front of the drafter.
    """
    scans = (
        (ClaimIssueType.INDEFINITE_TERM, _INDEFINITE_PATTERN,
         "Term of degree: {terms}. Definite only if the specification provides a standard "
         "for measuring the degree.",
         "Recite a measurable limit, or confirm the specification defines the term."),
        (ClaimIssueType.OPTIONAL_LANGUAGE, _OPTIONAL_PATTERN,
         "Optional language: {terms}. Language that makes a limitation optional leaves the "
         "claim scope unclear.",
         'Recite the feature positively, or move it to a dependent claim.'),
        (ClaimIssueType.EXEMPLARY_LANGUAGE, _EXEMPLARY_PATTERN,
         "Exemplary language: {terms}. Examples in a claim leave it unclear whether the "
         "example limits the claim.",
         "Remove the example or recite the limitation it is meant to cover."),
        (ClaimIssueType.TRADEMARK, _TRADEMARK_PATTERN,
         "Trademark symbol in the claim: {terms}. A trademark identifies a source, not a "
         "product, so it does not define claim scope.",
         "Recite the material or component by its technical name."),
    )

    for issue_type, pattern, template, suggestion in scans:
        for issue in _scan_blocks(claim, issue_type, pattern, template, suggestion):
            yield issue


def _scan_blocks(
    claim: Claim, issue_type: ClaimIssueType, pattern: re.Pattern,
    template: str, suggestion: str,
) -> Iterator[ClaimIssue]:
    locations: List[FindingLocation] = []
    terms: List[str] = []

    for block in _blocks(claim):
        for match in pattern.finditer(block.text):
            if issue_type == ClaimIssueType.INDEFINITE_TERM and _INDEFINITE_EXCEPTIONS.search(
                block.text[max(0, match.start() - 12):match.end() + 12]
            ):
                continue
            locations.append(_location(block, match.start(), match.end()))
            if match.group(0).lower() not in [t.lower() for t in terms]:
                terms.append(match.group(0))

    if not locations:
        return

    quoted = ", ".join(f'"{term}"' for term in terms[:6])
    if len(terms) > 6:
        quoted += f", and {len(terms) - 6} more"

    yield _issue(
        issue_type, claim.number,
        template.format(terms=quoted),
        Severity.WARNING,
        suggestion=suggestion,
        term=terms[0] if terms else "",
        locations=locations,
    )


def check_reference_numerals(claim: Claim) -> Iterator[ClaimIssue]:
    """
    Reference numerals in a claim must be in parentheses (37 CFR 1.75(d)(1)).

    A bare number is only flagged when nothing around it explains it -- "claim 3",
    "FIG. 2", "at least 2", "10 mm" and anything already parenthesised are left alone.
    """
    locations: List[FindingLocation] = []
    numerals: List[str] = []

    for block in _blocks(claim):
        for match in _REFERENCE_NUMERAL_PATTERN.finditer(block.text):
            before = block.text[:match.start()].rstrip()
            if _NUMERAL_CONTEXT_EXCEPTION.search(before):
                continue
            after = block.text[match.end():match.end() + 12].lstrip()
            if re.match(r"(?:mm|cm|m|nm|um|%|degrees?|deg|hz|khz|mhz|ghz|volts?|v\b)", after, re.I):
                continue
            locations.append(_location(block, match.start(), match.end()))
            if match.group(1) not in numerals:
                numerals.append(match.group(1))

    if not locations:
        return

    yield _issue(
        ClaimIssueType.REFERENCE_NUMERAL, claim.number,
        f"Claim {claim.number} contains bare numeral(s) "
        f"{', '.join(numerals[:6])}. A reference numeral used in a claim must be enclosed "
        f"in parentheses.",
        Severity.WARNING,
        suggestion="Write the reference numeral in parentheses, e.g. \"a housing (108)\".",
        term=numerals[0] if numerals else "",
        locations=locations,
    )


# -- amendment status -----------------------------------------------------------------

# Status identifiers that do say a claim is being amended now.
_AMENDMENT_STATUSES = {
    ClaimStatus.CURRENTLY_AMENDED, ClaimStatus.WITHDRAWN_AND_AMENDED, ClaimStatus.NEW,
}


def check_amendment_status(claim: Claim) -> Iterator[ClaimIssue]:
    """
    A claim edited with tracked changes must say so in its status identifier
    (37 CFR 1.121(c)): "(Currently Amended)", or "(New)" for an added claim.

    Only claims whose tracked edits were lined up with the parsed claims carry
    ``tracked_edits``; see :meth:`DocumentLoader._attach_tracked_edits`.
    """
    if not claim.metadata.get("tracked_edits"):
        return

    status, _ = split_status_marker(claim.claim_text or "")
    if status in _AMENDMENT_STATUSES:
        return

    current = f' (it is marked "({status.label})")' if status else " (it has none)"
    yield _issue(
        ClaimIssueType.AMENDED_WITHOUT_STATUS, claim.number,
        f"Claim {claim.number} is amended, but its status identifier does not reflect "
        f"the amendment{current}.",
        Severity.ERROR,
        suggestion='Change the status identifier to one that indicates a current '
                   'amendment, such as "(Currently Amended)".',
    )
