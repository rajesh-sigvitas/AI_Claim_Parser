import re
from typing import Tuple, List

class NormalizationEngine:
    """
    Normalization Engine responsible for converting extracted text 
    into a clean representation suitable for parsing.
    Must never change legal wording.
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
        claim_start = re.compile(r'^\s*(?:claim\s+)?\d+\.(?!\d)', re.IGNORECASE)
        
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
        
        return text, operations
