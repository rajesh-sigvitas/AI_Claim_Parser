"""
Renders the Claim Master report.

The layout follows the reference report: a title block, a table of contents with dotted
leaders, then the numbered sections, each introduced by its Roman numeral and, where the
reference carries one, a footnote explaining how to read it.

Conventions worth stating:

* Every analysed section opens with a status banner.  Green means the section was checked
  and nothing was found ("No errors found for this section."); red or amber means it found
  something, and the banner lists what, so a reader can triage the report from the banners
  alone.  The contents page repeats the same verdicts as a summary table.
* A section whose analyser has not run says it was not analysed.  "Nothing found" and
  "not checked" are different statements and the report never blurs them.
* Section III prints the claim and its findings side by side, with ``{1}``-style markers
  in the claim text keyed to numbered explanations in the right column.  The marker sits
  immediately after the words it is about, which is why findings carry character offsets.
"""
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from loguru import logger
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.analysis.antecedent.claim_walker import HEADER_INDEX, iter_claim_blocks
from app.analysis.antecedent.suggestion import SuggestionGenerator
from app.analysis.claim_errors.models import ClaimIssue
from app.analysis.hierarchy.models import (
    ClaimCategory,
    ClaimNode,
    ClaimStatus,
    HierarchyResult,
    ParentIssue,
)
from app.analysis.models import AntecedentFinding, FindingType, Severity
from app.models.claim import Claim
from app.report.claim_tree import build_forest
from app.report.models import CMReport, ReportSection

FONT = "Times-Roman"
FONT_BOLD = "Times-Bold"
BODY_SIZE = 11.5
CELL_SIZE = 10.5

MARGIN = 0.9 * inch
CONTENT_WIDTH = LETTER[0] - 2 * MARGIN
CELL_PADDING = 6

# Claim layout inside a table cell: each body level steps in this far from the preamble,
# and a list marker such as "(a)" hangs this far to the left of its text.
CLAIM_STEP = 16.0
MARKER_HANG = 18.0

# A section III row taller than the space left splits inside the row rather than moving
# whole to the next page.  ReportLab's default tries a between-rows split first, which
# places the remainder -- repeated header and all -- on the same page, printing a header
# row mid-page.  The value is also the smallest fragment, in points, either half may be,
# so a row never leaves a one-line sliver at the foot of a page.
ROW_SPLIT = dict(splitByRow=0, splitInRow=40)

NO_ERRORS_TEXT = "No errors found for this section."

# (foreground, background) per status.
_OK = ("#1E7B34", "#EAF6EC")
_ERROR = ("#B3261E", "#FDECEA")
_WARNING = ("#9A5B00", "#FFF4E0")
_PENDING = ("#666666", "#F2F2F2")

_SYMBOL_FONT = "CMSymbols"
_SYMBOL_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _status_icons() -> Dict[str, str]:
    """
    Check, cross and warning glyphs for the status banners.

    Times has none of them, and the base-14 ZapfDingbats font is not embedded, so each
    viewer substitutes its own -- several draw a plain box for all three.  DejaVu Sans is
    embedded instead, which pins the glyph; without it the banners fall back to text.
    """
    try:
        if _SYMBOL_FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(_SYMBOL_FONT, str(_SYMBOL_FONT_PATH)))
    except Exception as error:                       # pragma: no cover - font missing
        logger.warning(f"Status glyph font unavailable ({error}); using text markers.")
        return {"ok": "[OK]", "error": "[X]", "warning": "[!]"}

    return {
        "ok": f'<font name="{_SYMBOL_FONT}">\u2714</font>',
        "error": f'<font name="{_SYMBOL_FONT}">\u2718</font>',
        "warning": f'<font name="{_SYMBOL_FONT}">\u26A0</font>',
    }


_ICONS = _status_icons()

# Footnotes reproduced from the reference report.
_FOOTNOTES = {
    ReportSection.CLAIMS_HIERARCHY: (
        "Graphical claim trees only: the type of each claim is indicated by its colour. "
        "Independent claims are grey inside. Claims with invalid parent numbers are dotted. "
        "If present, status indicators will be provided in brackets next to the claim numbers."
    ),
    ReportSection.CLAIM_ERRORS: (
        "Fix suggestions/detailed explanations are not repeated for the same types of "
        "issues to preserve space."
    ),
}

# Footnote markers, numbered as in the reference report.
_FOOTNOTE_NUMBER = {
    ReportSection.CLAIMS_HIERARCHY: "1",
    ReportSection.CLAIM_ERRORS: "2",
}

_SEVERITY_COLOR = {
    Severity.ERROR: _ERROR[0],
    Severity.WARNING: _WARNING[0],
}

# How each section III finding type is named in the report, in the order they are listed.
_ANTECEDENT_LABELS = {
    FindingType.MISSING_ANTECEDENT: "Missing antecedent basis",
    FindingType.REVERSE_ANTECEDENT: "Reverse antecedent",
    FindingType.LIMITING_PREAMBLE: "Limiting preamble?",
    FindingType.SINGULAR_PLURAL: "Singular/plural mismatch?",
}

_ANALYSED_SECTIONS = (
    ReportSection.CLAIMS_HIERARCHY,
    ReportSection.CLAIM_ERRORS,
    ReportSection.ANTECEDENTS,
)


# -- section verdicts -------------------------------------------------------


@dataclass
class SectionStatus:
    """The verdict a section's banner and the summary table print."""

    kind: str                              # "ok" | "error" | "warning" | "pending"
    headline: str
    details: List[str] = field(default_factory=list)

    @property
    def colors(self) -> Tuple[str, str]:
        return {"ok": _OK, "error": _ERROR, "warning": _WARNING}.get(self.kind, _PENDING)


def section_status(report: CMReport, section: ReportSection) -> SectionStatus:
    """What a section found, in the words its banner uses."""
    if section == ReportSection.CLAIMS_HIERARCHY:
        return _hierarchy_status(report.hierarchy)
    if section == ReportSection.CLAIM_ERRORS:
        return _claim_error_status(report.claim_errors)
    if section == ReportSection.ANTECEDENTS:
        return _antecedent_status(report.antecedents)
    return SectionStatus("pending", "Not analysed")


def _hierarchy_status(result: Optional[HierarchyResult]) -> SectionStatus:
    if result is None:
        return SectionStatus("pending", "Not analysed")
    if not result.claim_count:
        return SectionStatus("warning", "No claims were found in the document.")

    invalid = [result.node(number) for number in result.invalid_parent_claims]
    invalid = [node for node in invalid if node is not None]
    if not invalid:
        return SectionStatus("ok", NO_ERRORS_TEXT)

    return SectionStatus(
        "error",
        f"{_plural(len(invalid), 'claim')} with an invalid parent reference.",
        [_describe_parent_issues(node) for node in invalid],
    )


def _describe_parent_issues(node: ClaimNode) -> str:
    parts = []
    for parent, issue in sorted(node.parent_issues.items()):
        if issue == ParentIssue.SELF_REFERENCE:
            parts.append("refers to itself")
        elif issue == ParentIssue.MISSING_CLAIM:
            parts.append(f"depends on claim {parent}, which does not exist")
        elif issue == ParentIssue.FORWARD_REFERENCE:
            parts.append(f"depends on claim {parent}, which follows it")
        else:
            parts.append(f"has a circular dependency through claim {parent}")
    return f"Claim {node.number} " + "; ".join(parts) + "."


def _claim_error_status(result) -> SectionStatus:
    if result is None:
        return SectionStatus("pending", "Not analysed")
    if result.is_clean:
        return SectionStatus("ok", NO_ERRORS_TEXT)

    grouped: Dict[str, List[Optional[int]]] = {}
    for issue in result.issues:
        grouped.setdefault(issue.label, []).append(issue.claim_number)

    details = []
    for label, claims in grouped.items():
        numbers = sorted({n for n in claims if n is not None})
        if not numbers:
            where = "claim set"
        elif len(numbers) == 1:
            where = f"claim {numbers[0]}"
        else:
            where = f"claims {_compress(numbers)}"
        details.append(f"{label}: {where}")

    return SectionStatus(
        "error" if result.errors else "warning",
        f"{_counts(result.errors, result.warnings)} found.",
        details,
    )


def _antecedent_status(result) -> SectionStatus:
    if result is None:
        return SectionStatus("pending", "Not analysed")
    if not result.findings:
        return SectionStatus("ok", NO_ERRORS_TEXT)

    errors = sum(1 for f in result.findings if f.severity == Severity.ERROR)
    warnings = len(result.findings) - errors

    details = []
    for finding_type, label in _ANTECEDENT_LABELS.items():
        claims = [f.claim_number for f in result.findings if f.type == finding_type]
        if not claims:
            continue
        numbers = sorted(set(claims))
        noun = "claim" if len(numbers) == 1 else "claims"
        details.append(f"{label.rstrip('?')}: {len(claims)} in {noun} {_compress(numbers)}")

    return SectionStatus(
        "error" if errors else "warning",
        f"{_counts(errors, warnings)} found.",
        details,
    )


def _standalone_antecedent_status(report: CMReport, status: SectionStatus) -> SectionStatus:
    """
    Section III's verdict, reworded for a report that is only about antecedents.

    "No errors found for this section" reads oddly when there is only one section, and a
    claim-less upload has to say it found no claims rather than report a clean result.
    """
    if not report.claim_count:
        return SectionStatus("warning", "No claims were found in the document.")
    if report.antecedents is None:
        return SectionStatus("error", "The antecedent analysis could not be completed.",
                             [report.notes.get("III", "")] if report.notes.get("III") else [])
    if status.kind == "ok":
        return SectionStatus("ok", "No antecedent or reverse antecedent errors found.")
    return status


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _counts(errors: int, warnings: int) -> str:
    parts = []
    if errors:
        parts.append(_plural(errors, "error"))
    if warnings:
        parts.append(_plural(warnings, "warning"))
    return " and ".join(parts) or "No issues"


def _compress(numbers: Iterable[int]) -> str:
    """"1-8, 10, 12-14" -- a claim list short enough to read at a glance."""
    ordered = sorted(set(numbers))
    if not ordered:
        return ""
    runs, start, previous = [], ordered[0], ordered[0]
    for number in ordered[1:]:
        if number == previous + 1:
            previous = number
            continue
        runs.append((start, previous))
        start = previous = number
    runs.append((start, previous))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


# -- renderer ---------------------------------------------------------------


class CMReportGenerator:
    """Builds the report PDF from a :class:`CMReport`."""

    def __init__(self, output_dir: str = "outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.styles = self._create_styles()
        self._claim_styles: Dict[Tuple[int, bool], ParagraphStyle] = {}
        self._explained: set = set()
        # True while rendering the standalone antecedent report, which has no other
        # sections for the text to point at.
        self._standalone = False

    # -- styles -------------------------------------------------------------

    def _create_styles(self) -> Dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()["Normal"]
        body = ParagraphStyle(
            "CMBody", parent=base, fontName=FONT, fontSize=BODY_SIZE, leading=15,
            alignment=TA_LEFT, spaceAfter=0,
        )
        cell = ParagraphStyle("CMCell", parent=body, fontSize=CELL_SIZE, leading=13.5)

        return {
            "Body": body,
            "Cell": cell,
            "Title": ParagraphStyle(
                "CMTitle", parent=body, fontName=FONT_BOLD, fontSize=19, leading=24,
                spaceAfter=4,
            ),
            "Meta": ParagraphStyle(
                "CMMeta", parent=body, fontSize=11, leading=14.5,
                textColor=colors.HexColor("#444444"),
            ),
            "PageTitle": ParagraphStyle(
                "CMPageTitle", parent=body, fontName=FONT_BOLD, fontSize=12.5,
                leading=16, alignment=TA_CENTER, spaceBefore=18, spaceAfter=10,
            ),
            "TOCEntry": ParagraphStyle("CMTOCEntry", parent=body, leading=18),
            "SectionHeading": ParagraphStyle(
                "CMSectionHeading", parent=body, fontName=FONT_BOLD, fontSize=13.5,
                leading=17, keepWithNext=True,
            ),
            "SectionNumber": ParagraphStyle(
                "CMSectionNumber", parent=body, fontSize=13.5, leading=17,
            ),
            "Banner": ParagraphStyle(
                "CMBanner", parent=body, fontName=FONT_BOLD, fontSize=11.5, leading=15,
            ),
            "BannerDetail": ParagraphStyle(
                "CMBannerDetail", parent=body, fontSize=10.5, leading=14,
                leftIndent=16, spaceBefore=1,
            ),
            "Footnote": ParagraphStyle(
                "CMFootnote", parent=body, fontSize=9, leading=12,
                textColor=colors.HexColor("#555555"),
            ),
            "Note": ParagraphStyle(
                "CMNote", parent=body, fontSize=10.5, leading=14,
                textColor=colors.HexColor("#444444"), spaceBefore=6,
            ),
            "CellHead": ParagraphStyle(
                "CMCellHead", parent=cell, fontName=FONT_BOLD, alignment=TA_CENTER,
            ),
            "CellBold": ParagraphStyle("CMCellBold", parent=cell, fontName=FONT_BOLD),
            # Table ALIGN does not reach inside a Paragraph; centring has to be a style.
            "CellCenter": ParagraphStyle("CMCellCenter", parent=cell, alignment=TA_CENTER),
            "CellBoldCenter": ParagraphStyle(
                "CMCellBoldCenter", parent=cell, fontName=FONT_BOLD, alignment=TA_CENTER,
            ),
            "Legend": ParagraphStyle("CMLegend", parent=body, fontSize=10, leading=14.5),
            "ClaimText": ParagraphStyle(
                "CMClaimText", parent=cell, spaceBefore=0, spaceAfter=0,
            ),
        }

    def _claim_style(self, level: int, has_marker: bool) -> ParagraphStyle:
        """
        Body-element style for claim text in a cell.

        Level 1 sits one step in from the preamble, so an element never reads as the
        preamble's wrapped continuation; each deeper level steps in again.  A marked
        element hangs its "(a)" to the left so the text after it stays aligned.
        """
        level = max(1, min(9, level or 1))
        key = (level, has_marker)
        if key not in self._claim_styles:
            indent = CLAIM_STEP * level
            self._claim_styles[key] = ParagraphStyle(
                f"CMClaimLevel{level}{'Marker' if has_marker else ''}",
                parent=self.styles["ClaimText"],
                leftIndent=indent + (MARKER_HANG if has_marker else 0),
                firstLineIndent=-MARKER_HANG if has_marker else 0,
                spaceBefore=3,
            )
        return self._claim_styles[key]

    # -- entry point --------------------------------------------------------

    def generate(self, report: CMReport, output_path: Optional[str] = None) -> str:
        output_path = self._output_path(output_path, prefix="CM_Report")
        document = self._document(output_path, "Patent Document Report", "Claim Master report")
        self._standalone = False

        # "Fix suggestions/detailed explanations are not repeated for the same types of
        # issues to preserve space" -- the reference report's own convention, and the
        # reason a twenty-claim set does not print the same paragraph forty times.
        self._explained = set()

        story: List = []
        self._build_cover(report, story)
        self._build_toc(report, story)
        self._build_summary(report, story)
        story.append(PageBreak())
        self._build_hierarchy(report, story)
        self._build_claim_errors(report, story)
        self._build_antecedents(report, story)
        self._build_pending_sections(report, story)

        document.build(story, onLaterPages=self._page_footer, onFirstPage=self._page_footer)
        logger.info(f"Claim Master report generated: {output_path}")
        return output_path

    def generate_antecedent_report(
        self, report: CMReport, output_path: Optional[str] = None
    ) -> str:
        """
        The standalone antecedent report: section III's analysis on its own.

        It uses the same claim layout, status banner and page flow as the Claim Master
        report, so the two read alike, but it has no contents page or section numbering --
        those would point at sections this report does not contain.
        """
        output_path = self._output_path(output_path, prefix="Antecedent_Analysis")
        document = self._document(
            output_path, "Antecedent Analysis Report", "Antecedent basis analysis"
        )
        self._explained = set()
        self._standalone = True
        try:
            story: List = []
            self._build_cover(report, story, title="Antecedent Analysis Report")
            story.append(Spacer(1, 14))
            story.append(Paragraph(
                "Every definite reference in the claims (&ldquo;the&nbsp;X&rdquo;, "
                "&ldquo;said&nbsp;X&rdquo;) is checked for antecedent basis in its own claim "
                "or in a claim it depends from. A reference with no introduction is a "
                "<b>missing antecedent</b>; one that comes before its introduction is a "
                "<b>reverse antecedent</b>.",
                self.styles["Note"],
            ))
            story.append(Spacer(1, 12))
            self._build_antecedents(report, story)
            document.build(
                story, onLaterPages=self._page_footer, onFirstPage=self._page_footer
            )
        finally:
            self._standalone = False

        logger.info(f"Antecedent report generated: {output_path}")
        return output_path

    def _output_path(self, output_path: Optional[str], prefix: str) -> str:
        """A fresh path for the report; an existing file is never overwritten."""
        if not output_path:
            return str(self.output_dir / self._new_filename(prefix))
        if Path(output_path).exists():
            return str(Path(output_path).parent / self._new_filename(prefix))
        return output_path

    @staticmethod
    def _document(output_path: str, title: str, subject: str) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            output_path,
            pagesize=LETTER,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=0.85 * inch, bottomMargin=0.85 * inch,
            title=title,
            author="Claim Parser AI",
            subject=subject,
        )

    @staticmethod
    def _new_filename(prefix: str = "CM_Report") -> str:
        return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}.pdf"

    @staticmethod
    def _page_footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont(FONT, 9)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawCentredString(document.pagesize[0] / 2, 0.5 * inch, str(canvas.getPageNumber()))
        canvas.restoreState()

    # -- cover, contents and summary ----------------------------------------

    def _build_cover(
        self, report: CMReport, story: List, title: str = "Patent Document Report"
    ) -> None:
        story.append(Paragraph(self._escape(title), self.styles["Title"]))
        story.append(Paragraph(
            f"Document Name: {self._escape(report.document_name or 'Untitled')}",
            self.styles["Meta"],
        ))
        story.append(Paragraph(
            f"Date: {report.generated or time.strftime('%d %b %Y')}", self.styles["Meta"]
        ))

        facts = []
        if report.claim_count:
            facts.append(f"Claims: {report.claim_count}")
        if report.page_count:
            facts.append(f"Pages: {report.page_count}")
        if report.cancelled_claims:
            facts.append("Cancelled: " + _compress(report.cancelled_claims))
        if facts:
            story.append(Paragraph(" &nbsp;|&nbsp; ".join(facts), self.styles["Meta"]))

    def _build_toc(self, report: CMReport, story: List) -> None:
        story.append(Paragraph("<u>TABLE OF CONTENTS</u>", self.styles["PageTitle"]))

        number_width, status_width = 0.5 * inch, 1.1 * inch
        title_width = CONTENT_WIDTH - number_width - status_width

        rows = []
        for section in ReportSection:
            label = f"<b>{self._escape(section.title)}</b> "
            # Fill the rest of the line with dots rather than a fixed run: a fixed run
            # wraps the long section IV title onto a second, dots-only line.
            used = stringWidth(section.title + " ", FONT_BOLD, BODY_SIZE)
            dot = stringWidth(".", FONT, BODY_SIZE)
            leader = "." * max(0, int((title_width - used) / dot) - 2)
            status = "not analysed" if report.is_pending(section) else ""
            rows.append([
                Paragraph(f"{section.value}.", self.styles["TOCEntry"]),
                Paragraph(f'{label}<font color="#AAAAAA">{leader}</font>', self.styles["TOCEntry"]),
                Paragraph(
                    f'<font color="#888888" size="9">{status}</font>' if status else "",
                    self.styles["TOCEntry"],
                ),
            ])

        table = Table(rows, colWidths=[number_width, title_width, status_width])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        story.append(table)

    def _build_summary(self, report: CMReport, story: List) -> None:
        """The verdict of every section, in one table, before any detail."""
        story.append(Paragraph("<u>SUMMARY OF FINDINGS</u>", self.styles["PageTitle"]))

        rows = [[
            Paragraph("", self.styles["CellHead"]),
            Paragraph("Section", self.styles["CellHead"]),
            Paragraph("Result", self.styles["CellHead"]),
        ]]
        backgrounds = []
        for position, section in enumerate(ReportSection, start=1):
            status = section_status(report, section)
            foreground, background = status.colors
            if status.kind == "pending":
                result = f'<font color="{foreground}">Not analysed</font>'
            else:
                icon = _ICONS.get(status.kind, "")
                headline = "No errors found" if status.kind == "ok" else status.headline.rstrip(".")
                result = f'<font color="{foreground}">{icon}&nbsp; <b>{self._escape(headline)}</b></font>'
            rows.append([
                Paragraph(f"{section.value}.", self.styles["Cell"]),
                Paragraph(self._escape(section.title), self.styles["Cell"]),
                Paragraph(result, self.styles["Cell"]),
            ])
            if status.kind != "pending":
                backgrounds.append(("BACKGROUND", (2, position), (2, position),
                                    colors.HexColor(background)))

        table = Table(
            rows, colWidths=[0.6 * inch, CONTENT_WIDTH - 2.9 * inch, 2.3 * inch], repeatRows=1,
        )
        table.setStyle(TableStyle(self._table_commands() + backgrounds))
        story.append(table)

    # -- section scaffolding ------------------------------------------------

    def _section_heading(self, section: ReportSection, story: List) -> None:
        """
        "I.    Claims Hierarchy" with the numeral in its own column, as in the reference.

        The numeral sits in a fixed-width first column so the titles line up down the
        report regardless of whether the numeral is "I." or "VIII.".
        """
        marker = _FOOTNOTE_NUMBER.get(section)
        title = f"<u>{self._escape(section.title)}</u>"
        if marker:
            title += f'<super><font size="8">{marker}</font></super>'

        table = Table(
            [[
                Paragraph(f"{section.value}.", self.styles["SectionNumber"]),
                Paragraph(title, self.styles["SectionHeading"]),
            ]],
            colWidths=[0.5 * inch, CONTENT_WIDTH - 0.5 * inch],
        )
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(table)

    def _status_banner(self, status: SectionStatus, story: List) -> None:
        """The section verdict, in a tinted box with a coloured rule down its left edge."""
        foreground, background = status.colors
        icon = _ICONS.get(status.kind, "")

        content = [Paragraph(
            f'<font color="{foreground}">{icon}&nbsp;&nbsp;{self._escape(status.headline)}</font>',
            self.styles["Banner"],
        )]
        for detail in status.details:
            content.append(Paragraph(
                f'<font color="{foreground}">&bull;&nbsp; {self._escape(detail)}</font>',
                self.styles["BannerDetail"],
            ))

        banner = Table([[content]], colWidths=[CONTENT_WIDTH])
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
            ("LINEBEFORE", (0, 0), (0, -1), 3.5, colors.HexColor(foreground)),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        story.append(banner)
        story.append(Spacer(1, 14))

    def _footnote(self, section: ReportSection, story: List) -> None:
        text = _FOOTNOTES.get(section)
        if not text:
            return
        marker = _FOOTNOTE_NUMBER.get(section, "")
        story.append(Spacer(1, 12))
        story.append(HRFlowable(
            width=2.2 * inch, thickness=0.5, color=colors.HexColor("#666666"),
            spaceBefore=0, spaceAfter=4, hAlign="LEFT",
        ))
        story.append(Paragraph(
            f'<super><font size="7">{marker}</font></super> <i>{self._escape(text)}</i>',
            self.styles["Footnote"],
        ))

    def _pending(self, story: List) -> None:
        story.append(Paragraph(
            "This section analyses the specification and is not included in this report.",
            self.styles["Note"],
        ))

    # -- I. claims hierarchy ------------------------------------------------

    def _build_hierarchy(self, report: CMReport, story: List) -> None:
        section = ReportSection.CLAIMS_HIERARCHY
        self._section_heading(section, story)

        result = report.hierarchy
        status = section_status(report, section)
        if status.kind == "pending":
            self._pending(story)
            return

        self._status_banner(status, story)
        if not result.claim_count:
            self._footnote(section, story)
            return

        story.append(Paragraph(
            f"The claim set contains <b>{result.claim_count}</b> claims: "
            f"<b>{len(result.independent_claims)}</b> independent "
            f"({_compress(result.independent_claims) or 'none'}) and "
            f"<b>{len(result.dependent_claims)}</b> dependent.",
            self.styles["Body"],
        ))
        story.append(Spacer(1, 14))

        forest = build_forest(result)
        if forest is not None:
            story.append(forest)
            story.append(Spacer(1, 18))

        self._claim_tree_table(report, result, story)
        story.append(Spacer(1, 14))
        self._hierarchy_legend(story)
        self._footnote(section, story)

    def _claim_tree_table(self, report: CMReport, result: HierarchyResult, story: List) -> None:
        """One row per tree: which independent claim, of what type, and what hangs off it."""
        rows = [[
            Paragraph("Independent claim", self.styles["CellHead"]),
            Paragraph("Claim type", self.styles["CellHead"]),
            Paragraph("Dependent claims", self.styles["CellHead"]),
            Paragraph("Claims in tree", self.styles["CellHead"]),
        ]]

        for tree in result.trees:
            node = result.node(tree.root)
            root = f"<b>{self._escape(node.display if node else str(tree.root))}</b>"
            if node is not None and not node.is_independent:
                root += f'<br/><font color="{_ERROR[0]}" size="9">invalid parent</font>'

            category = node.category if node else ClaimCategory.UNKNOWN
            dependents = [number for number in tree.nodes if number != tree.root]

            rows.append([
                Paragraph(root, self.styles["CellCenter"]),
                Paragraph(
                    f'<font color="{category.color}"><b>{self._escape(category.label)}</b></font>',
                    self.styles["Cell"],
                ),
                Paragraph(_compress(dependents) or "None", self.styles["Cell"]),
                Paragraph(str(len(tree.nodes)), self.styles["CellCenter"]),
            ])

        table = Table(
            rows, repeatRows=1,
            colWidths=[1.35 * inch, 1.75 * inch, CONTENT_WIDTH - 4.15 * inch, 1.05 * inch],
        )
        table.setStyle(TableStyle(self._table_commands()))
        story.append(table)

        if report.cancelled_claims:
            story.append(Paragraph(
                "Cancelled by amendment and not analysed: claims "
                f"{_compress(report.cancelled_claims)}.",
                self.styles["Note"],
            ))

    def _hierarchy_legend(self, story: List) -> None:
        """
        Both legends, printed in full.

        Every claim type is listed even when the set uses only two of them: the legend
        explains the colour scheme itself, and a reader comparing two reports should not
        have to work out whether a colour is absent or merely unused here.
        """
        names = [
            f'<font color="{category.color}"><b>{self._escape(category.label)}</b></font>'
            for category in ClaimCategory if category != ClaimCategory.UNKNOWN
        ]
        story.append(Paragraph(
            "<u>Claim type color legend</u>: " + "; ".join(names), self.styles["Legend"],
        ))
        story.append(Paragraph(
            "<u>Status indicator legend</u>: "
            + "; ".join(
                f"<b>[{status.value}]</b>=&ldquo;{status.label}&rdquo;" for status in ClaimStatus
            ),
            self.styles["Legend"],
        ))

    # -- II. claim errors ---------------------------------------------------

    def _build_claim_errors(self, report: CMReport, story: List) -> None:
        section = ReportSection.CLAIM_ERRORS
        story.append(PageBreak())
        self._section_heading(section, story)

        status = section_status(report, section)
        if status.kind == "pending":
            self._pending(story)
            return

        self._status_banner(status, story)
        result = report.claim_errors
        if not result.is_clean:
            rows = [[
                Paragraph("Claim", self.styles["CellHead"]),
                Paragraph("Severity", self.styles["CellHead"]),
                Paragraph("Error/Warning", self.styles["CellHead"]),
            ]]
            for issue in result.issues:
                color = _SEVERITY_COLOR.get(issue.severity, "#333333")
                rows.append([
                    Paragraph(
                        str(issue.claim_number) if issue.claim_number else "All",
                        self.styles["CellBoldCenter"],
                    ),
                    Paragraph(
                        f'<font color="{color}"><b>{issue.severity.value.title()}</b></font>',
                        self.styles["CellCenter"],
                    ),
                    self._issue_cell(issue),
                ])

            table = Table(
                rows, repeatRows=1,
                colWidths=[0.65 * inch, 0.95 * inch, CONTENT_WIDTH - 1.6 * inch],
            )
            table.setStyle(TableStyle(self._table_commands()))
            story.append(table)

        self._footnote(section, story)

    def _issue_cell(self, issue: ClaimIssue) -> List:
        color = _SEVERITY_COLOR.get(issue.severity, "#333333")
        flowables = [Paragraph(
            f'<font color="{color}"><b>{self._escape(issue.label)}</b></font>: '
            f"{self._escape(issue.message)}",
            self.styles["Cell"],
        )]
        if issue.suggestion and self._first_of_type(f"II:{issue.type.value}"):
            flowables.append(Paragraph(
                f'<font color="#1F5FA8">Suggested fix: {self._escape(issue.suggestion)}</font>',
                self.styles["Cell"],
            ))
        if issue.authority:
            flowables.append(Paragraph(
                f'<font color="#777777" size="9">{self._escape(issue.authority)}</font>',
                self.styles["Cell"],
            ))
        return flowables

    # -- III. antecedents ---------------------------------------------------

    def _build_antecedents(self, report: CMReport, story: List) -> None:
        section = ReportSection.ANTECEDENTS
        if not self._standalone:
            story.append(PageBreak())
            self._section_heading(section, story)

        status = section_status(report, section)
        if self._standalone:
            status = _standalone_antecedent_status(report, status)
        if status.kind == "pending":
            self._pending(story)
            return

        self._status_banner(status, story)
        result = report.antecedents
        if result is None or not result.findings:
            return

        claims = {claim.number: claim for claim in self._claims_of(report)}
        flagged = sorted({f.claim_number for f in result.findings if f.claim_number in claims})
        if not flagged:
            return

        claim_width = 3.95 * inch
        findings_width = CONTENT_WIDTH - claim_width
        inner_width = claim_width - 2 * CELL_PADDING
        # One number column for the whole table, sized to the widest number in it, so
        # every claim's text starts at the same x whether it is claim 1 or claim 15.
        number_width = stringWidth(f"{max(flagged)}.", FONT, CELL_SIZE) + 6

        rows = [[
            Paragraph("Claim", self.styles["CellHead"]),
            Paragraph("Error/Warning", self.styles["CellHead"]),
        ]]
        for claim_number in flagged:
            findings = [f for f in result.findings if f.claim_number == claim_number]
            numbering = {id(finding): position for position, finding in enumerate(findings, 1)}
            rows.append([
                self._claim_cell(claims[claim_number], findings, numbering,
                                 number_width, inner_width),
                self._findings_cell(findings, numbering,
                                    self._dependency_note(report, claim_number)),
            ])

        # A claim with many findings can be taller than a page, and a table row that
        # cannot split raises a LayoutError instead of continuing overleaf.
        table = Table(
            rows, colWidths=[claim_width, findings_width], repeatRows=1, **ROW_SPLIT,
        )
        table.setStyle(TableStyle(self._table_commands()))
        story.append(table)

    @staticmethod
    def _claims_of(report: CMReport) -> List[Claim]:
        return list(report.claim_document.claims) if report.claim_document else []

    def _claim_cell(
        self, claim: Claim, findings: List[AntecedentFinding], numbering: Dict[int, int],
        number_width: float, width: float,
    ) -> Table:
        """
        The claim, laid out as in the claim PDF, with {n} markers in its text.

        The number gets its own column and the text another, which is what keeps the
        preamble's wrapped lines, and every element under it, on exact vertical lines --
        a hanging indent only aligns when the indent happens to match the number's width.
        """
        markers = self._markers_by_block(findings, numbering)
        blocks = list(iter_claim_blocks(claim))

        lead = next((b for b in blocks if b.index == HEADER_INDEX), None)
        body_blocks = [b for b in blocks if b.index != HEADER_INDEX]
        # A headerless claim's first markerless block is its opening text; it belongs on
        # the number's line, exactly as the claim PDF draws it.
        if lead is None and body_blocks and not (body_blocks[0].marker or "").strip() \
                and body_blocks[0].level <= 1:
            lead = body_blocks.pop(0)

        text = []
        if lead is not None:
            text.append(Paragraph(
                self._mark(lead.text, markers.get(lead.index, [])), self.styles["ClaimText"],
            ))
        for block in body_blocks:
            marked = self._mark(block.text, markers.get(block.index, []))
            has_marker = bool((block.marker or "").strip())
            if has_marker:
                marked = f"{self._escape(block.marker)} {marked}"
            text.append(Paragraph(marked, self._claim_style(block.level, has_marker)))

        cell = Table(
            [[Paragraph(f"{claim.number}.", self.styles["ClaimText"]), text or ""]],
            colWidths=[number_width, width - number_width],
            **ROW_SPLIT,
        )
        cell.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return cell

    @staticmethod
    def _markers_by_block(
        findings: List[AntecedentFinding], numbering: Dict[int, int]
    ) -> Dict[int, List[Tuple[int, int, int]]]:
        """Maps a block index to the (start, end, marker number) spans inside it."""
        by_block: Dict[int, List[Tuple[int, int, int]]] = {}
        for finding in findings:
            locations = finding.locations or ([finding.location] if finding.location else [])
            for location in locations:
                if location is None or location.element_index is None:
                    continue
                if location.char_start is None or location.char_end is None:
                    continue
                by_block.setdefault(location.element_index, []).append(
                    (location.char_start, location.char_end, numbering[id(finding)])
                )

        for spans in by_block.values():
            spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))
        return by_block

    def _mark(self, text: str, spans: List[Tuple[int, int, int]]) -> str:
        """Bolds each flagged term and appends its ``{n}`` marker."""
        if not spans:
            return self._escape(text)

        out, cursor = [], 0
        for start, end, number in spans:
            start = max(0, min(start, len(text)))
            end = max(start, min(end, len(text)))
            if start < cursor:                 # overlapping spans: keep the first
                continue
            out.append(self._escape(text[cursor:start]))
            out.append(
                f"<b>{self._escape(text[start:end])}</b>"
                f'<super><font size="8">{{{number}}}</font></super>'
            )
            cursor = end
        out.append(self._escape(text[cursor:]))
        return "".join(out)

    def _dependency_note(self, report: CMReport, claim_number: int) -> Optional[str]:
        """
        Why a claim with a broken dependency reports so many missing antecedents.

        A dependent claim inherits every limitation of the claims it depends from, so when
        its parent reference is invalid it inherits nothing and each term it reuses is
        reported.  Saying that once, at the top of the cell, keeps the reader from chasing
        each finding separately: they all have the same cause.
        """
        if report.hierarchy is None:
            return None
        node = report.hierarchy.node(claim_number)
        if node is None or not node.has_invalid_parent:
            return None
        # The standalone report has no section II to point at, so it names the problem.
        reason = (
            _describe_parent_issues(node) if self._standalone
            else "Its parent reference is invalid (see section II)."
        )
        return (
            f"Claim {claim_number} cannot inherit antecedent basis. {reason} The findings "
            f"below follow from that, and most will resolve once the dependency is corrected."
        )

    def _findings_cell(
        self, findings: List[AntecedentFinding], numbering: Dict[int, int],
        note: Optional[str] = None,
    ) -> List:
        flowables = []
        if note:
            flowables.append(Paragraph(
                f'<font color="{_WARNING[0]}"><i>{self._escape(note)}</i></font>',
                self.styles["Cell"],
            ))
            flowables.append(Spacer(1, 6))

        for finding in findings:
            number = numbering[id(finding)]
            color = _SEVERITY_COLOR.get(finding.severity, "#333333")
            label, rest = self._split_label(finding)
            flowables.append(Paragraph(
                f"<b>{{{number}}}</b> "
                f'<font color="{color}"><b>{self._escape(label)}</b></font>: '
                f"{self._escape(rest)}",
                self.styles["Cell"],
            ))

            suggestion = SuggestionGenerator.generate(finding) or ""
            if suggestion and self._first_of_type(f"III:{finding.type.value}"):
                flowables.append(Paragraph(
                    f'<font color="#1F5FA8">Suggested fix: {self._escape(suggestion)}</font>',
                    self.styles["Cell"],
                ))
            flowables.append(Spacer(1, 6))
        return flowables

    @staticmethod
    def _split_label(finding: AntecedentFinding) -> Tuple[str, str]:
        """
        The finding's type name and the rest of its message.

        Advisory messages already open with their name ("Limiting preamble?: ...");
        that prefix is lifted off so the name can be coloured without printing it twice.
        """
        label = _ANTECEDENT_LABELS.get(finding.type, finding.type.value.title())
        message = finding.message or ""
        if message.startswith(label):
            return label, message[len(label):].lstrip(" :").strip()
        return label, message

    # -- IV to VIII ---------------------------------------------------------

    def _build_pending_sections(self, report: CMReport, story: List) -> None:
        pending = [section for section in ReportSection if section not in _ANALYSED_SECTIONS]
        if not pending:
            return

        story.append(PageBreak())
        for section in pending:
            self._section_heading(section, story)
            self._pending(story)
            story.append(Spacer(1, 12))

    # -- shared -------------------------------------------------------------

    def _first_of_type(self, key: str) -> bool:
        """True the first time an issue type is seen, so its explanation prints once."""
        if key in self._explained:
            return False
        self._explained.add(key)
        return True

    @staticmethod
    def _table_commands() -> List[tuple]:
        return [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDED")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B5B5B5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), CELL_PADDING),
            ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PADDING),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]

    @staticmethod
    def _escape(text: str) -> str:
        """Escapes text for reportlab's mini-XML parser."""
        if not text:
            return ""
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
