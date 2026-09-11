import re
from collections import Counter
from typing import Tuple, List

# PDF extraction drops the space between a function word and the article after it:
# "one or more ofthe moment".
_GLUED_ARTICLE = re.compile(
    r"\b(of|to|in|on|at|by|for|from|with|and|or|into|onto|upon|through)(the)\b"
    r"|\b(of)(an|a)\b",
    re.IGNORECASE,
)

# Candidate glued compounds ("usercharacteristic") and the spaced pairs that justify
# splitting them.  A long token is only split when the same two words occur, spaced,
# at least twice elsewhere in the text -- evidence the glued form is an extraction
# artifact rather than a real compound.
_SPACED_PAIR = re.compile(r"(?=\b([A-Za-z]{3,})[ \t]+([A-Za-z]{3,})\b)")
_LONG_WORD = re.compile(r"\b[A-Za-z]{7,}\b")
_MIN_PAIR_EVIDENCE = 2

# A colon introduces a list only after an introducing word ("comprising:", "to:",
# "wherein:", "consisting of:").  After any other word -- "by the first user:
# determine ..." -- it is a semicolon the extraction mangled, and left in place it
# makes the segmenter nest every later limitation under the one before it.
_LIST_INTRODUCERS = {
    "comprising", "comprises", "comprise", "including", "includes", "include",
    "consisting", "consists", "containing", "contains", "having", "has", "have",
    "of", "to", "for", "by", "wherein", "whereby", "that", "following", "least",
    "steps", "operations", "acts", "further", "claim", "claims", "claimed", "is", "are",
}
_COLON = re.compile(r"\b([A-Za-z][\w-]*)(\s*):(?=\s+(?!an?\b)[a-z])")

class NormalizationEngine:
    """
    Normalization Engine responsible for converting extracted text 
    into a clean representation suitable for parsing.
    Must never change legal wording -- the extraction repairs below only restore
    spacing and punctuation the extractor lost.
    """
    def __init__(self):
        # OCR cleanup patterns
        self.ocr_fixes = [
            (re.compile(r'\bclalm\b', re.IGNORECASE), "claim"),
            (re.compile(r'\bclain\b', re.IGNORECASE), "claim"),
            (re.compile(r'\bcornprlsing\b', re.IGNORECASE), "comprising"),
            (re.compile(r'\bcornprising\b', re.IGNORECASE), "comprising"),
            (re.compile(r'\bwhereln\b', re.IGNORECASE), "wherein")
        ]
        
    def normalize(self, extracted_text: str) -> Tuple[str, List[str]]:
        """
        Executes the normalization pipeline.
        Returns the normalized text and a list of operations performed.
        """
        operations = []
        text = extracted_text
        
        # 1. Page Header/Footer/Number Removal
        text = re.sub(r'^\s*(?:Page\s+\d+|\d+\s+of\s+\d+|-\s*\d+\s*-)\s*$', '', text, flags=re.MULTILINE|re.IGNORECASE)
        operations.append("page_artifacts_removed")
        
        # 2. Duplicate blank lines removal
        text = re.sub(r'\n{3,}', '\n\n', text)
        operations.append("whitespace_cleaned")
        
        # 3. OCR Cleanup (Conservative)
        original_text = text
        for pattern, replacement in self.ocr_fixes:
            text = pattern.sub(replacement, text)
        if text != original_text:
            operations.append("ocr_cleanup_applied")
        
        # 4. Line Merging
        # - If a line ends with a hyphen, remove the hyphen and join directly with the next line (fixes "diago- nally").
        # - Otherwise, join with a space, unless the next line starts with a claim boundary (e.g. "2. The system...").
        # - Or if it's a double newline, keep the paragraph break.
        
        # First fix hyphenated breaks
        text = re.sub(r'([a-zA-Z])-\s*\n\s*([a-zA-Z])', r'\1\2', text)
        
        # Then we join lines that don't look like they begin a new claim
        lines = text.split('\n')
        merged_lines = []
        # A claim may open with a bare number ("12."), a renumbering ("12.[13.]") or a
        # bracketed number alone ("[12.]", a claim cancelled by an amendment).  All three
        # must survive as line starts, otherwise the splitter cannot see the boundary and
        # the claim is merged into the one above it.
        claim_start = re.compile(r'^\s*(?:claim\s+)?(?:\d+\s*\.(?!\d)|\[\s*\d+\s*\.?\s*\])', re.IGNORECASE)
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                merged_lines.append("")
                continue
                
            if merged_lines and merged_lines[-1] != "":
                # If the current line starts a new claim, don't merge it with the previous line
                if claim_start.match(stripped):
                    merged_lines.append(stripped)
                else:
                    # Merge with a space
                    merged_lines[-1] = merged_lines[-1] + " " + stripped
            else:
                merged_lines.append(stripped)
                
        # Filter out empty lines to leave double newlines as single newlines between paragraphs
        text = '\n'.join(merged_lines)
        text = re.sub(r'\n{2,}', '\n\n', text)

        # 5. Extraction repairs.  These run after line merging so a colon at the end of
        # a line sees the word that starts the next one.
        text, glued = self._split_glued_articles(text)
        if glued:
            operations.append(f"glued_articles_split:{glued}")
        text, compounds = self._split_glued_compounds(text)
        if compounds:
            operations.append(f"glued_compounds_split:{compounds}")
        text, colons = self._repair_stray_colons(text)
        if colons:
            operations.append(f"stray_colons_repaired:{colons}")

        return text, operations

    @staticmethod
    def _split_glued_articles(text: str) -> Tuple[str, int]:
        """"ofthe" -> "of the"."""
        count = 0

        def repl(m):
            nonlocal count
            count += 1
            word, article = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            return f"{word} {article}"

        return _GLUED_ARTICLE.sub(repl, text), count

    @staticmethod
    def _split_glued_compounds(text: str) -> Tuple[str, int]:
        """"usercharacteristic" -> "user characteristic", when the text itself says so."""
        pairs = Counter(
            (m.group(1).lower(), m.group(2).lower()) for m in _SPACED_PAIR.finditer(text)
        )
        joined = {
            first + second: (len(first), n)
            for (first, second), n in pairs.items() if n >= _MIN_PAIR_EVIDENCE
        }
        if not joined:
            return text, 0

        seen = Counter(w.lower() for w in _LONG_WORD.findall(text))
        count = 0

        def repl(m):
            nonlocal count
            word = m.group(0)
            split = joined.get(word.lower())
            if split is None or seen[word.lower()] >= split[1]:
                return word
            count += 1
            return f"{word[:split[0]]} {word[split[0]:]}"

        return _LONG_WORD.sub(repl, text), count

    @staticmethod
    def _repair_stray_colons(text: str) -> Tuple[str, int]:
        """"by the first user: determine ..." -> "by the first user; determine ..."."""
        count = 0

        def repl(m):
            nonlocal count
            if m.group(1).lower() in _LIST_INTRODUCERS:
                return m.group(0)
            count += 1
            return f"{m.group(1)}{m.group(2)};"

        return _COLON.sub(repl, text), count
