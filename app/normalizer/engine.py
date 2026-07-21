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
        
        # 4. Line Merging (Heuristic: merge lines if they don't end in punctuation or start with a number/enum)
        # We will let the HierarchyBuilder handle specific element extraction, but we can clean up obvious mid-sentence breaks.
        # For patent claims, it's often safer to rely on semicolons and enumerations for breaks.
        # We'll just normalize trailing spaces.
        text = '\n'.join(line.strip() for line in text.split('\n'))
        
        return text, operations
