import uuid
import time
from pathlib import Path
from loguru import logger
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

from app.models.document import ClaimDocument
from app.models.claim import Claim, ClaimElement

class PDFGenerator:
    """
    Generates a professionally formatted, USPTO-compliant PDF
    from a canonical ClaimDocument using ReportLab.
    """

    def __init__(self, output_dir: str = "outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Standard USPTO formatting settings
        self.font_name = "Times-Roman"
        
        # Try to register a Unicode-capable font for fallback
        font_dir = Path("/usr/share/fonts/truetype/dejavu")
        self.has_fallback = False
        if (font_dir / "DejaVuSerif.ttf").exists():
            try:
                pdfmetrics.registerFont(TTFont('DejaVuSerif', str(font_dir / "DejaVuSerif.ttf")))
                pdfmetrics.registerFont(TTFont('DejaVuSerif-Bold', str(font_dir / "DejaVuSerif-Bold.ttf")))
                pdfmetrics.registerFont(TTFont('DejaVuSerif-Italic', str(font_dir / "DejaVuSerif-Italic.ttf")))
                pdfmetrics.registerFont(TTFont('DejaVuSerif-BoldItalic', str(font_dir / "DejaVuSerif-BoldItalic.ttf")))
                registerFontFamily(
                    'DejaVuSerif', 
                    normal='DejaVuSerif', 
                    bold='DejaVuSerif-Bold', 
                    italic='DejaVuSerif-Italic', 
                    boldItalic='DejaVuSerif-BoldItalic'
                )
                self.has_fallback = True
            except Exception as e:
                logger.warning(f"Failed to register DejaVuSerif fonts: {e}")

        self.font_size = 12
        self.leading = 14
        
        self.styles = self._create_styles()

    def _create_styles(self) -> dict:
        """Create standard Paragraph styles with exact hanging indentations."""
        styles = getSampleStyleSheet()
        
        # Base style
        base_style = ParagraphStyle(
            'USPTO_Base',
            parent=styles['Normal'],
            fontName=self.font_name,
            fontSize=self.font_size,
            leading=self.leading,
            alignment=TA_LEFT,
            spaceBefore=0,
            spaceAfter=0
        )
        
        custom_styles = {
            "Title": ParagraphStyle(
                'USPTO_Title',
                parent=base_style,
                spaceAfter=12,
                keepWithNext=True
            ),
            # Claim root (Preamble / independent claim body)
            # 1. A system comprising... -> hanging indent for the number
            "ClaimRoot": ParagraphStyle(
                'USPTO_ClaimRoot',
                parent=base_style,
                leftIndent=24,         # Body wraps to 24pt
                firstLineIndent=-24,   # Number hangs out to 0pt
                spaceBefore=12,
            )
        }
        
        # Create styles for elements with varying indentation levels.
        # Level 1 sits at 24pt, i.e. flush with the claim body, and every deeper
        # level steps in by another 24pt.
        #
        # Two variants per level, because the hanging indent is only correct when
        # something actually hangs in it:
        #   - "Element_Level_N"        flat block; every line, first included,
        #                              starts at the element indent so the text
        #                              reads as one aligned block.
        #   - "Element_Level_N_Marker" hanging indent for "(a)", "(i)", etc.; the
        #                              marker sits at the element indent and the
        #                              wrapped lines align with the text after it.
        # Using the hanging variant for markerless elements is what used to
        # outdent their first line and indent every wrapped line beneath it.
        for level in range(1, 10):
            indent_pt = level * 24
            custom_styles[f"Element_Level_{level}"] = ParagraphStyle(
                f'USPTO_Element_{level}',
                parent=base_style,
                leftIndent=indent_pt,
                firstLineIndent=0,
                spaceBefore=6
            )
            custom_styles[f"Element_Level_{level}_Marker"] = ParagraphStyle(
                f'USPTO_Element_{level}_Marker',
                parent=base_style,
                leftIndent=indent_pt + 24,
                firstLineIndent=-24,
                spaceBefore=6
            )

        return custom_styles

    def _element_style(self, level: int, marker: str = None) -> ParagraphStyle:
        """Picks the paragraph style for an element, clamping stray levels."""
        level = max(1, min(9, level or 1))
        if (marker or "").strip():
            return self.styles[f"Element_Level_{level}_Marker"]
        return self.styles[f"Element_Level_{level}"]

    @staticmethod
    def _opens_claim_line(marker: str, level: int) -> bool:
        """
        True when an element is really the opening text of the claim.

        Some claims come back from the parser with an empty header because no
        preamble/transition could be split off (a dependent claim whose body is
        one semicolon list, for instance).  Rendering those as-is prints the
        number on a line of its own with the claim text starting one line below
        it.  A markerless top-level element is that missing opening text, so it
        is drawn on the number's line instead.
        """
        return not (marker or "").strip() and (level or 1) <= 1

    def generate(self, claim_document: ClaimDocument, output_path: str = None) -> str:
        """
        Generates the PDF. If output_path is None, generates a UUID-based filename
        in the default outputs directory.
        """
        if not output_path:
            filename = f"Patent_{int(time.time())}_{uuid.uuid4().hex[:6]}.pdf"
            output_path = str(self.output_dir / filename)
            
        # Ensure we never overwrite
        path_obj = Path(output_path)
        if path_obj.exists():
            filename = f"Patent_{int(time.time())}_{uuid.uuid4().hex[:6]}.pdf"
            output_path = str(path_obj.parent / filename)

        logger.info(f"Generating PDF at {output_path}")

        # Document setup: A4, 1-inch margins
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=inch,
            leftMargin=inch,
            topMargin=inch,
            bottomMargin=inch,
            title="Patent Claims",
            author="Claim Parser AI",
            creator="Claim Parser AI Engine",
            subject="USPTO Patent Claims Reconstruction",
            keywords="patent, claims, uspto"
        )

        story = []

        # Title
        story.append(Paragraph("What is claimed is:", self.styles["Title"]))

        # Build claims
        for claim in claim_document.claims:
            self._build_claim_story(claim, story)

        doc.build(story)
        logger.info(f"PDF successfully generated: {output_path}")
        return output_path

    def _build_claim_story(self, claim: Claim, story: list):
        """Adds a single claim to the PDF story flow."""

        # We need to construct the root text which is the claim number + preamble + transition
        # Or if the parser didn't successfully split preamble/transition, we use raw claim_text
        # But wait, we have `claim.formatted_text` or we can reconstruct it.
        # It's safer to reconstruct it so we can apply styles to elements.

        header_text = claim.header.strip() if claim.header else ""
        elements = list(claim.elements)

        # No header: promote the claim's first line so the number never stands
        # alone with its text starting on the line below.
        if not header_text and elements and self._opens_claim_line(elements[0].marker, elements[0].level):
            lead = elements.pop(0)
            header_text = lead.text.strip()
            elements = list(lead.children) + elements

        root_text = f"{claim.number}. {header_text}" if header_text else f"{claim.number}."

        # Add root paragraph
        story.append(Paragraph(self._escape(root_text), self.styles["ClaimRoot"]))

        # Add elements recursively
        for el in elements:
            self._build_element_story(el, story)

    def _build_element_story(self, el: ClaimElement, story: list):
        """Recursively adds elements to the story with correct indentation."""
        style = self._element_style(el.level, el.marker)

        # The text might contain HTML from XML. ReportLab Paragraphs support basic XML like <b>, <i>, <sub>, <sup>.
        # But we must escape stray < and > not part of tags.
        # Actually, ReportLab supports <b>, <i>, <u>, <sub>, <sup> exactly as requested!
        # We should just escape & first, then we can pass the string to Paragraph.
        # If there's a marker, reconstruct the full text for display
        display_text = f"{el.marker.strip()} {el.text.strip()}" if el.marker else el.text.strip()
        safe_text = self._escape_and_preserve_tags(display_text)
        
        story.append(Paragraph(safe_text, style))
        
        for child in el.children:
            self._build_element_story(child, story)
            
    def _escape(self, text: str) -> str:
        """Escapes special characters for ReportLab XML parser."""
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if getattr(self, 'has_fallback', False):
            import re
            text = re.sub(r'([^\x00-\x7F]+)', r'<font name="DejaVuSerif">\1</font>', text)
        return text
        
    def _escape_and_preserve_tags(self, text: str) -> str:
        """
        Escapes text but preserves <b>, <i>, <u>, <sub>, <sup>, <claim-ref>.
        Since <claim-ref> is not a valid ReportLab tag, we strip it but keep contents.
        """
        import re
        # First escape all &
        text = text.replace("&", "&amp;")
        
        # Replace <claim-ref> with nothing, keeping inner text
        text = re.sub(r'<claim-ref[^>]*>(.*?)</claim-ref>', r'\1', text)
        
        # Define allowed tags
        allowed_tags = ['b', 'i', 'u', 'sub', 'sup']
        
        # We need a regex that matches <tag> and </tag>
        # Every < not part of an allowed tag must become &lt;
        # We can split the string by tags
        pattern = r'(</?(?:' + '|'.join(allowed_tags) + r')[^>]*>)'
        parts = re.split(pattern, text, flags=re.IGNORECASE)
        
        escaped_parts = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                # This is a tag, keep it as is
                escaped_parts.append(part)
            else:
                # This is text, escape < and >
                escaped_text = part.replace("<", "&lt;").replace(">", "&gt;")
                if getattr(self, 'has_fallback', False):
                    escaped_text = re.sub(r'([^\x00-\x7F]+)', r'<font name="DejaVuSerif">\1</font>', escaped_text)
                escaped_parts.append(escaped_text)
                
        return "".join(escaped_parts)
