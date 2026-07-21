"""
Central regex pattern library for rule-based patent claim parsing.
All regex patterns used by the parser modules are defined here.
No regex should be scattered across other modules.
"""
import re

# =============================================================================
# Claim Statement Headers
# =============================================================================
# Detects the start of the claims section in patent text
CLAIM_STATEMENT_PATTERN = re.compile(
    r'^\s*(?:What\s+is\s+claimed\s+is\s*[:\.]|'
    r'The\s+invention\s+claimed\s+is\s*[:\.]|'
    r'We\s+claim\s*[:\.]|'
    r'I\s+claim\s*[:\.]|'
    r'CLAIMS?\s*[:\.]?)\s*$',
    re.IGNORECASE | re.MULTILINE
)

# =============================================================================
# Claim Numbering Patterns
# =============================================================================
# Detects claim boundary: "1. ", " 1.", "Claim 1.", but NOT decimals like "3.5"
# Requires the number to be followed by a period and a space or end-of-line,
# or to be preceded by "claim" keyword.
CLAIM_BOUNDARY_PATTERN = re.compile(
    r'(?:^|\n)\s*(?:claim\s+)?(\d+)\.\s+',
    re.IGNORECASE
)

# Stricter version for splitting: anchored to start of line
CLAIM_SPLIT_PATTERN = re.compile(
    r'(?=(?:^|\n)\s*(?:claim\s+)?(\d+)\.\s+)',
    re.IGNORECASE
)

# Extracts claim number and body from a single claim block
CLAIM_NUMBER_EXTRACT = re.compile(
    r'^\s*(?:claim\s+)?(\d+)\.\s+(.*)',
    re.IGNORECASE | re.DOTALL
)

# =============================================================================
# Claim Reference Patterns (Dependency Detection)
# =============================================================================
# "The system of claim 1", "The method according to claim 3"
DEPENDENCY_PATTERN = re.compile(
    r'(?:of|according\s+to|in|as\s+(?:recited|defined|set\s+forth)\s+in)\s+claim\s+(\d+)',
    re.IGNORECASE
)

# Single reference: "claim 1"
SINGLE_CLAIM_REF = re.compile(r'\bclaim\s+(\d+)\b', re.IGNORECASE)

# Range reference: "claims 1-5", "claims 1 through 5"
RANGE_CLAIM_REF = re.compile(
    r'\bclaims?\s+(\d+)\s*(?:-|to|through)\s*(\d+)\b',
    re.IGNORECASE
)

# List reference: "claims 1, 2, and 3" or "claims 1 and 3"
LIST_CLAIM_REF = re.compile(
    r'\bclaims?\s+(\d+(?:\s*,\s*\d+)*(?:\s*,?\s*(?:and|or)\s+\d+)?)\b',
    re.IGNORECASE
)

# =============================================================================
# Transition Phrases
# =============================================================================
TRANSITION_PHRASES = [
    "consisting essentially of",
    "consisting of",
    "comprising",
    "including",
    "having",
    "containing",
    "wherein",
    "whereby",
    "configured to",
    "adapted to",
    "further comprising",
    "characterized in that",
]

# Ordered longest-first to match greedily
TRANSITION_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(p) for p in TRANSITION_PHRASES) + r')\b',
    re.IGNORECASE
)

# Specifically for the main claim transition (the first structural one after preamble)
PRIMARY_TRANSITION_PATTERN = re.compile(
    r'\b(comprising|consisting\s+of|consisting\s+essentially\s+of|including|having|containing)\b',
    re.IGNORECASE
)

# =============================================================================
# Enumeration Patterns
# =============================================================================
# Alphabetic: (a), (b), (c)
ENUM_ALPHA_LOWER = re.compile(r'^\s*\(([a-z])\)\s*', re.MULTILINE)
# Alphabetic uppercase: (A), (B), (C)
ENUM_ALPHA_UPPER = re.compile(r'^\s*\(([A-Z])\)\s*', re.MULTILINE)
# Roman: (i), (ii), (iii), (iv), (v), (vi), (vii), (viii), (ix), (x)
ENUM_ROMAN = re.compile(
    r'^\s*\((i{1,3}|iv|vi{0,3}|ix|x)\)\s*',
    re.IGNORECASE | re.MULTILINE
)
# Numeric sub-enumeration: (1), (2), (3) or 1), 2), 3)
ENUM_NUMERIC = re.compile(r'^\s*\(?(\d+)\)\s*', re.MULTILINE)

# Inline enumeration markers for splitting within a single claim text line
INLINE_ENUM_PATTERN = re.compile(
    r'(?:\s|^)(\([a-z]\)|\([A-Z]\)|\((?:i{1,3}|iv|vi{0,3}|ix|x)\)|\(\d+\))\s+',
    re.IGNORECASE
)

# =============================================================================
# Semicolon Parsing
# =============================================================================
# Matches the empty string immediately after a semicolon that is NOT inside parentheses
SEMICOLON_SPLIT = re.compile(r'(?<=;)(?![^(]*\))')

# =============================================================================
# Preamble Detection
# =============================================================================
PREAMBLE_KEYWORDS = [
    r"A\s+method",
    r"A\s+system",
    r"A\s+process",
    r"A\s+device",
    r"A\s+apparatus",
    r"An?\s+apparatus",
    r"A\s+machine",
    r"A\s+composition",
    r"An?\s+article",
    r"A\s+computer[\s-]+readable\s+medium",
    r"A\s+non-transitory\s+computer[\s-]+readable\s+(?:storage\s+)?medium",
    r"A\s+seed",
    r"A\s+plant",
    r"A\s+vehicle",
    r"An?\s+assembly",
    r"A\s+kit",
    r"A\s+pharmaceutical\s+composition",
    r"A\s+compound",
    r"An?\s+integrated\s+circuit",
]

PREAMBLE_PATTERN = re.compile(
    r'^\s*(' + '|'.join(PREAMBLE_KEYWORDS) + r')\b',
    re.IGNORECASE
)

# =============================================================================
# Claim Category Detection
# =============================================================================
CATEGORY_PATTERNS = {
    "method": re.compile(r'\b(?:method|process)\b', re.IGNORECASE),
    "system": re.compile(r'\bsystem\b', re.IGNORECASE),
    "apparatus": re.compile(r'\b(?:apparatus|device|machine)\b', re.IGNORECASE),
    "composition": re.compile(r'\bcomposition\b', re.IGNORECASE),
    "computer-readable medium": re.compile(
        r'\b(?:computer[\s-]*readable\s+(?:storage\s+)?medium|non-transitory)', re.IGNORECASE
    ),
    "article": re.compile(r'\barticle\b', re.IGNORECASE),
    "product": re.compile(r'\bproduct\b', re.IGNORECASE),
}

# =============================================================================
# Page Artifacts (for normalization)
# =============================================================================
PAGE_NUMBER_PATTERN = re.compile(
    r'^\s*(?:Page\s+\d+(?:\s+of\s+\d+)?|-\s*\d+\s*-|\[\d+\])\s*$',
    re.MULTILINE | re.IGNORECASE
)

HEADER_FOOTER_PATTERN = re.compile(
    r'^\s*(?:US\s*\d{1,3}(?:,\d{3})*\s*[A-Z]\d*|'
    r'Patent\s+No\.\s*\d|'
    r'Sheet\s+\d+\s+of\s+\d+)\s*$',
    re.MULTILINE | re.IGNORECASE
)
