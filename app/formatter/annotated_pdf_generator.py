"""
Renders the claim set with every antecedent defect highlighted in place.

Highlighting is driven by the character offsets recorded on each finding, so
the exact words that triggered the finding are marked.  The previous version
called ``text.replace(term, annotation, 1)``, which marked the first substring
that merely looked like the term -- frequently the wrong occurrence, and
nothing at all when the parser had normalised the surface form.

Claim text is walked with :func:`iter_claim_blocks`, the same traversal the
analyser used, so block indices on findings always line up with what is drawn.
"""
import time
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.analysis.antecedent.claim_walker import HEADER_INDEX, iter_claim_blocks
from app.analysis.antecedent.suggestion import SuggestionGenerator
from app.analysis.models import AntecedentFinding, FindingType
from app.formatter.pdf_generator import PDFGenerator
from app.models.claim import Claim
from app.models.document import ClaimDocument

# Background / foreground pairs used for in-text highlighting.
STYLE_BY_TYPE = {
    FindingType.MISSING_ANTECEDENT: ("#FFD4D4", "#A61B1B", "Missing antecedent basis"),
    FindingType.REVERSE_ANTECEDENT: ("#FFE6B3", "#8A5200", "Reverse antecedent"),
    FindingType.POSSIBLY_MISSING_ANTECEDENT:
        ("#FFF2C2", "#7A5C00", "Possibly missing antecedent basis?"),
}
_DEFAULT_STYLE = ("#E6E6E6", "#333333", "Finding")


class AnnotatedPDFGenerator(PDFGenerator):
    def __init__(self, findings: List[AntecedentFinding], output_dir: str = "outputs"):
        super().__init__(output_dir)
        self.findings = list(findings)

        # Findings are numbered once, and that number is what appears both in
        # the summary table and as the superscript beside the highlight.
        self._numbers: Dict[int, int] = {id(f): i + 1 for i, f in enumerate(self.findings)}

        base = getSampleStyleSheet()
        self.styles["ReportTitle"] = ParagraphStyle(
            "AntecedentReportTitle", parent=base["Normal"], fontName=self.font_name,
            fontSize=16, leading=20, spaceAfter=6, alignment=TA_LEFT,
        )
        self.styles["SectionTitle"] = ParagraphStyle(
            "AntecedentSectionTitle", parent=base["Normal"], fontName=self.font_name,
            fontSize=13, leading=17, spaceBefore=16, spaceAfter=8, alignment=TA_LEFT,
        )
        self.styles["Meta"] = ParagraphStyle(
            "AntecedentMeta", parent=base["Normal"], fontName=self.font_name,
            fontSize=10, leading=13, textColor=colors.HexColor("#555555"), spaceAfter=2,
        )
        self.styles["Cell"] = ParagraphStyle(
            "AntecedentCell", parent=base["Normal"], fontName=self.font_name,
            fontSize=9, leading=12,
        )

    # -- text annotation ----------------------------------------------------

    def _escape(self, text: str) -> str:
        return self._escape_and_preserve_tags(text)

    def _spans_for_block(
        self, claim_number: int, block_index: int
    ) -> List[Tuple[int, int, AntecedentFinding]]:
        """Every highlight span that falls inside one claim block."""
        spans = []
        for finding in self.findings:
            if finding.claim_number != claim_number:
                continue
            for location in (finding.locations or ([finding.location] if finding.location else [])):
                if location is None or location.element_index != block_index:
                    continue
                if location.char_start is None or location.char_end is None:
                    continue
                spans.append((location.char_start, location.char_end, finding))

        # Left to right, and drop overlaps so the markup can never nest.
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        result, last_end = [], -1
        for start, end, finding in spans:
            if start >= last_end:
                result.append((start, end, finding))
                last_end = end
        return result

    def _annotate(self, text: str, claim_number: int, block_index: int) -> str:
        """Escapes `text` and wraps each defect span in a highlight."""
        spans = self._spans_for_block(claim_number, block_index)
        if not spans:
            return self._escape_and_preserve_tags(text)

        out, cursor = [], 0
        for start, end, finding in spans:
            start = max(0, min(start, len(text)))
            end = max(start, min(end, len(text)))
            if start > cursor:
                out.append(self._escape_and_preserve_tags(text[cursor:start]))

            back, fore, _ = STYLE_BY_TYPE.get(finding.type, _DEFAULT_STYLE)
            marked = self._escape_and_preserve_tags(text[start:end])
            number = self._numbers.get(id(finding), 0)
            out.append(
                f'<font backColor="{back}" color="{fore}"><b>{marked}</b></font>'
                f'<super><font color="{fore}" size="7">[{number}]</font></super>'
            )
            cursor = end

        out.append(self._escape_and_preserve_tags(text[cursor:]))
        return "".join(out)

    # -- report sections ----------------------------------------------------

    def _build_header(self, document: ClaimDocument, story: list):
        missing = sum(1 for f in self.findings if f.type == FindingType.MISSING_ANTECEDENT)
        reverse = sum(1 for f in self.findings if f.type == FindingType.REVERSE_ANTECEDENT)
        possible = sum(
            1 for f in self.findings if f.type == FindingType.POSSIBLY_MISSING_ANTECEDENT
        )

        story.append(Paragraph("Antecedent Analysis Report", self.styles["ReportTitle"]))
        story.append(Paragraph(
            f"Claims analysed: {document.claim_count} &nbsp;|&nbsp; "
            f"Findings: {len(self.findings)} "
            f"(missing antecedent: {missing}, reverse antecedent: {reverse}, "
            f"possibly missing: {possible})",
            self.styles["Meta"],
        ))
        story.append(Paragraph(
            f"Generated {time.strftime('%d %b %Y %H:%M')}", self.styles["Meta"]
        ))
        story.append(Spacer(1, 10))

        legend = []
        for finding_type, (back, fore, label) in STYLE_BY_TYPE.items():
            legend.append(
                f'<font backColor="{back}" color="{fore}"><b>&nbsp;{label}&nbsp;</b></font>'
            )
        story.append(Paragraph("&nbsp;&nbsp;".join(legend), self.styles["Meta"]))

    def _build_findings_table(self, story: list):
        story.append(Paragraph("Findings", self.styles["SectionTitle"]))

        if not self.findings:
            story.append(Paragraph(
                "No antecedent or reverse antecedent errors were detected.",
                self.styles["Cell"],
            ))
            return

        header = ["#", "Claim", "Type", "Term", "Issue and suggested fix"]
        rows = [[Paragraph(f"<b>{h}</b>", self.styles["Cell"]) for h in header]]

        for finding in self.findings:
            _, fore, label = STYLE_BY_TYPE.get(finding.type, _DEFAULT_STYLE)
            suggestion = SuggestionGenerator.generate(finding) or ""
            detail = self._escape_and_preserve_tags(finding.message)
            if suggestion:
                detail += (
                    f'<br/><font color="#1F5FA8">Suggested fix: '
                    f'{self._escape_and_preserve_tags(suggestion)}</font>'
                )
            rows.append([
                Paragraph(str(self._numbers[id(finding)]), self.styles["Cell"]),
                Paragraph(str(finding.claim_number), self.styles["Cell"]),
                Paragraph(f'<font color="{fore}"><b>{label}</b></font>', self.styles["Cell"]),
                Paragraph(self._escape_and_preserve_tags(finding.term), self.styles["Cell"]),
                Paragraph(detail, self.styles["Cell"]),
            ])

        table = Table(rows, colWidths=[18, 34, 96, 104, 210], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)

    def _build_claim_story(self, claim: Claim, story: list):
        """
        Renders one claim with its defects highlighted.

        Layout mirrors :class:`PDFGenerator` exactly -- same root/element styles,
        same promotion of a headerless claim's first block onto the number's
        line -- so the annotated report and the clean claim set line up
        page for page.
        """
        blocks = list(iter_claim_blocks(claim))
        flowables = []

        lead = next((b for b in blocks if b.index == HEADER_INDEX), None)
        body_blocks = [b for b in blocks if b.index != HEADER_INDEX]

        # Headerless claim: its opening text is the first markerless top-level
        # block, and it belongs on the number's line rather than below it.
        if lead is None and body_blocks and self._opens_claim_line(
            body_blocks[0].marker, body_blocks[0].level
        ):
            lead = body_blocks.pop(0)

        if lead is not None:
            body = self._annotate(lead.text, claim.number, lead.index)
            flowables.append(Paragraph(f"{claim.number}. {body}", self.styles["ClaimRoot"]))
        else:
            flowables.append(Paragraph(f"{claim.number}.", self.styles["ClaimRoot"]))

        for block in body_blocks:
            text = self._annotate(block.text, claim.number, block.index)
            if block.marker:
                text = f"{self._escape_and_preserve_tags(block.marker)} {text}"
            flowables.append(Paragraph(text, self._element_style(block.level, block.marker)))

        # Keep a short claim on one page; let a long one flow naturally.
        if len(flowables) <= 4:
            story.append(KeepTogether(flowables))
        else:
            story.extend(flowables)

    def generate(self, claim_document: ClaimDocument, output_path: str = None) -> str:
        if not output_path:
            output_path = str(self.output_dir / self._new_filename())
        elif Path(output_path).exists():
            output_path = str(Path(output_path).parent / self._new_filename())

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=inch, leftMargin=inch, topMargin=inch, bottomMargin=inch,
            title="Antecedent Analysis Report",
            author="Claim Parser AI",
            subject="Antecedent basis analysis",
        )

        story: list = []
        self._build_header(claim_document, story)
        self._build_findings_table(story)

        story.append(Paragraph("Claims", self.styles["SectionTitle"]))
        story.append(Paragraph("What is claimed is:", self.styles["Title"]))
        for claim in claim_document.claims:
            self._build_claim_story(claim, story)

        doc.build(story)
        return output_path

    @staticmethod
    def _new_filename() -> str:
        return f"Antecedent_Analysis_{int(time.time())}_{uuid.uuid4().hex[:6]}.pdf"
