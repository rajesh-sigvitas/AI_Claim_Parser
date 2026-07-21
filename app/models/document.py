from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from app.core.constants import InputType
from app.models.claim import Claim

class ClaimDocument(BaseModel):
    """
    The canonical representation of a patent claim document.
    Everything in the system revolves around producing and rendering this object.
    """
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata.")
    input_type: InputType = Field(..., description="The detected source input type.")
    confidence_score: float = Field(0.0, description="The parser's confidence in the reconstruction (0-100).")
    ocr_used: bool = Field(False, description="Whether OCR was required for this document.")
    
    # Claim collections
    claims: List[Claim] = Field(default_factory=list, description="The list of all parsed claims in sequential order.")
    
    # Output paths
    pdf_path: Optional[str] = Field(None, description="Path to the generated PDF representation.")
    
    @property
    def claim_count(self) -> int:
        return len(self.claims)
        
    @property
    def independent_claims(self) -> List[Claim]:
        from app.core.constants import ClaimType
        return [c for c in self.claims if c.claim_type == ClaimType.INDEPENDENT]
        
    @property
    def dependent_claims(self) -> List[Claim]:
        from app.core.constants import ClaimType
        return [c for c in self.claims if c.claim_type != ClaimType.INDEPENDENT]
        
    @property
    def claim_tree(self) -> Dict[int, List[int]]:
        """
        Builds a dependency tree mapping parent claim numbers to their children.
        """
        tree = {c.claim_number: [] for c in self.claims if c.parent_claim is None}
        for c in self.claims:
            if c.parent_claim is not None:
                if c.parent_claim not in tree:
                    tree[c.parent_claim] = []
                tree[c.parent_claim].append(c.claim_number)
        return tree
