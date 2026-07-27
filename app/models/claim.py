from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from app.core.constants import ClaimType, ElementType

class ClaimElement(BaseModel):
    """
    Represents a specific element or clause within a claim.
    Every part of a claim is broken down into elements for hierarchical reconstruction.
    """
    text: str = Field(..., description="The raw text of this element.")
    level: int = Field(0, description="The structural indentation level of this element (0 for parent claim, >0 for children).")
    marker: Optional[str] = Field(None, description="The list marker, e.g. (a), (i).")
    element_type: ElementType = Field(..., description="The type of this element (e.g., BODY_ELEMENT, WHEREIN_CLAUSE).")
    order: int = Field(0, description="The sequential order of this element within the claim.")
    children: List['ClaimElement'] = Field(default_factory=list, description="Nested child elements.")

class Claim(BaseModel):
    """
    Represents a single parsed patent claim.
    Contains the original text and the reconstructed structural elements.
    """
    number: int = Field(..., description="The numerical identifier of the claim.")
    claim_type: ClaimType = Field(..., description="Whether the claim is independent, dependent, etc.")
    parent_claim: Optional[int] = Field(None, description="The claim number this claim depends on, if any.")
    references: List[Dict[str, Any]] = Field(default_factory=list, description="All claim references parsed from the source.")
    claim_text: str = Field("", description="The raw, unformatted text of the complete claim.")
    
    # Reconstructed parts
    header: str = Field("", description="The claim header, e.g., 'A system comprising:'.")
    elements: List[ClaimElement] = Field(default_factory=list, description="The structural elements of the claim body.")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context or metadata.")

# Required for self-referencing models in Pydantic
ClaimElement.model_rebuild()
