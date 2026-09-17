"""
Word tracked changes, resolved before a document is read.

A draft under review carries its edits as tracked changes.  LibreOffice renders them
when it lays the document out: deleted and inserted words side by side ("configured
tofor generate generating"), and list numbers shown twice ("12.[13.]") wherever an edit
shifts the automatic numbering.  Read from that rendering, claim text contains words the
drafter removed, and claim numbers -- and with them every dependency -- are ambiguous.

The document is therefore read as it will stand once the edits are accepted: deletions
removed, insertions kept, property changes resolved to their new values, and Word's own
automatic numbering recomputed by LibreOffice from the accepted paragraphs.

Which claims were edited is still worth knowing -- an amended claim must carry a status
identifier saying so -- so :func:`claims_with_tracked_edits` reports it separately.
"""
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lxml import etree

logger = logging.getLogger(__name__)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MARK = "{urn:claim-parser}revised"      # transient flag, never serialized


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


# Revision records whose removal leaves the current (accepted) properties in place.
_PROPERTY_CHANGES = (
    "rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "tblGridChange",
    "tcPrChange", "trPrChange", "numberingChange",
)
# Range markers that carry no content of their own.
_RANGE_MARKERS = (
    "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd",
    "customXmlInsRangeStart", "customXmlInsRangeEnd", "customXmlDelRangeStart",
    "customXmlDelRangeEnd", "customXmlMoveFromRangeStart", "customXmlMoveFromRangeEnd",
    "customXmlMoveToRangeStart", "customXmlMoveToRangeEnd", "cellIns",
)
_TEXT_REVISIONS = ("ins", "del", "moveFrom", "moveTo")

# Parts of a .docx that can hold tracked changes.
_REVISABLE_PART = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
_REVISION_HINT = re.compile(rb"<w:(ins|del|moveFrom|moveTo|rPrChange|pPrChange)\b")


# -- accepting changes ---------------------------------------------------------


def has_tracked_changes(docx_bytes: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
            return any(
                _REVISION_HINT.search(archive.read(name))
                for name in archive.namelist() if _REVISABLE_PART.match(name)
            )
    except (zipfile.BadZipFile, KeyError):
        return False


def accept_tracked_changes(docx_bytes: bytes) -> bytes:
    """
    The same .docx with every tracked change accepted.

    Anything that is not a readable .docx (a binary .doc, a corrupt file) is returned
    unchanged: conversion still works, only without this cleanup.
    """
    try:
        source = zipfile.ZipFile(io.BytesIO(docx_bytes))
    except zipfile.BadZipFile:
        return docx_bytes

    output = io.BytesIO()
    changed = 0
    with source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if _REVISABLE_PART.match(info.filename) and _REVISION_HINT.search(data):
                try:
                    root = etree.fromstring(data)
                except etree.XMLSyntaxError:
                    target.writestr(info, data)
                    continue
                _accept(root)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                changed += 1
            target.writestr(info, data)

    if changed:
        logger.info("Accepted tracked changes in %d document part(s).", changed)
    return output.getvalue()


def _accept(root, mark_revised: bool = False) -> None:
    """
    Accepts every tracked change in one XML part, in place.

    With ``mark_revised`` each paragraph that held a text revision is flagged first, and
    the flag follows the paragraph through merges, so the caller can tell which accepted
    paragraphs were edited.
    """
    if mark_revised:
        for paragraph in root.iter(_q("p")):
            if any(True for tag in _TEXT_REVISIONS for _ in paragraph.iter(_q(tag))):
                paragraph.set(_MARK, "1")

    for tag in _PROPERTY_CHANGES + _RANGE_MARKERS:
        for element in list(root.iter(_q(tag))):
            _drop(element)

    # Deleted table rows go with their row.
    for marker in list(root.iter(_q("del"))):
        parent = marker.getparent()
        if parent is not None and parent.tag == _q("trPr"):
            row = parent.getparent()
            if row is not None and row.getparent() is not None:
                row.getparent().remove(row)

    # Paragraph marks: an inserted mark simply stays; a deleted mark joins the paragraph
    # to the one after it.  Collected before run-level deletions are removed, because
    # both are w:del elements.
    joined: List = []
    for marker in list(root.iter(_q("ins"), _q("del"))):
        parent = marker.getparent()
        if parent is None:
            continue
        if parent.tag == _q("rPr") and parent.getparent() is not None \
                and parent.getparent().tag == _q("pPr"):
            if marker.tag == _q("del"):
                joined.append(parent.getparent().getparent())
            parent.remove(marker)
        elif parent.tag == _q("trPr"):
            parent.remove(marker)

    for tag in ("del", "moveFrom"):           # deleted or moved-away text
        for element in list(root.iter(_q(tag))):
            _drop(element)
    for tag in ("ins", "moveTo"):             # inserted or moved-here text
        for element in list(root.iter(_q(tag))):
            _unwrap(element)

    for paragraph in joined:
        _join_with_next(paragraph)


def _drop(element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _unwrap(element) -> None:
    parent = element.getparent()
    if parent is None:
        return
    position = parent.index(element)
    for child in list(element):
        parent.insert(position, child)
        position += 1
    parent.remove(element)


def _join_with_next(paragraph) -> None:
    """Moves a paragraph's content to the start of the next one, as Word does."""
    following = paragraph.getnext()
    while following is not None and following.tag != _q("p"):
        following = following.getnext()
    if following is None or paragraph.getparent() is None:
        return

    properties = following.find(_q("pPr"))
    position = 0 if properties is None else following.index(properties) + 1
    for child in [c for c in paragraph if c.tag != _q("pPr")]:
        following.insert(position, child)
        position += 1
    if paragraph.get(_MARK):
        following.set(_MARK, "1")
    paragraph.getparent().remove(paragraph)


# -- which claims were edited ------------------------------------------------------

_CLAIMS_START = re.compile(
    r"^\s*(?:what\s+is\s+claimed|we\s+claim|i\s+claim|the\s+invention\s+claimed|claims?\s*:?\s*$)",
    re.IGNORECASE,
)
_CLAIMS_END = re.compile(r"^\s*abstract\b", re.IGNORECASE)


@dataclass
class ClaimEdits:
    """Automatically numbered claims in the accepted document, and which were edited."""

    claim_count: int
    edited: List[int] = field(default_factory=list)   # 1-based positions in the claim list


def claims_with_tracked_edits(docx_bytes: bytes) -> Optional[ClaimEdits]:
    """
    Which claims contain tracked insertions or deletions.

    Claims are the automatically numbered paragraphs between the claim statement and the
    abstract, counted in the accepted document -- the numbering Word itself would show.
    Returns None when the document has no tracked changes or no numbered claims, so a
    caller never attributes edits to claims it cannot line up.
    """
    if not has_tracked_changes(docx_bytes):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
            root = etree.fromstring(archive.read("word/document.xml"))
            styles = archive.read("word/styles.xml") if "word/styles.xml" in archive.namelist() else b""
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError):
        return None

    _accept(root, mark_revised=True)
    numbered_styles = _numbered_styles(styles)

    paragraphs = list(root.iter(_q("p")))
    texts = [_text(p) for p in paragraphs]
    start = next((i for i, t in enumerate(texts) if _CLAIMS_START.match(t)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(texts)) if _CLAIMS_END.match(texts[i])), len(texts))

    edited: List[bool] = []
    for paragraph in paragraphs[start + 1:end]:
        if _is_numbered(paragraph, numbered_styles):
            edited.append(False)
        if edited and paragraph.get(_MARK):
            edited[-1] = True

    if not edited:
        return None
    return ClaimEdits(
        claim_count=len(edited),
        edited=[position for position, was_edited in enumerate(edited, start=1) if was_edited],
    )


def _text(paragraph) -> str:
    return "".join(t.text or "" for t in paragraph.iter(_q("t")))


def _is_numbered(paragraph, numbered_styles: Dict[str, bool]) -> bool:
    """Numbered by its own properties, or else by its paragraph style.  numId 0 is "off"."""
    properties = paragraph.find(_q("pPr"))
    if properties is not None:
        numbering = properties.find(_q("numPr"))
        if numbering is not None:
            identifier = numbering.find(_q("numId"))
            return identifier is not None and identifier.get(_q("val")) != "0"
        style = properties.find(_q("pStyle"))
        if style is not None:
            return numbered_styles.get(style.get(_q("val")), False)
    return False


def _numbered_styles(styles_xml: bytes) -> Dict[str, bool]:
    """Paragraph styles that carry automatic numbering, following ``basedOn`` chains."""
    if not styles_xml:
        return {}
    try:
        root = etree.fromstring(styles_xml)
    except etree.XMLSyntaxError:
        return {}

    own: Dict[str, Optional[bool]] = {}
    based_on: Dict[str, str] = {}
    for style in root.iter(_q("style")):
        style_id = style.get(_q("styleId"))
        if not style_id:
            continue
        numbering = style.find(f"{_q('pPr')}/{_q('numPr')}")
        if numbering is not None:
            identifier = numbering.find(_q("numId"))
            own[style_id] = identifier is not None and identifier.get(_q("val")) != "0"
        parent = style.find(_q("basedOn"))
        if parent is not None:
            based_on[style_id] = parent.get(_q("val"))

    resolved: Dict[str, bool] = {}
    for style_id in set(own) | set(based_on):
        seen, current = set(), style_id
        while current and current not in seen:
            seen.add(current)
            if current in own:
                resolved[style_id] = bool(own[current])
                break
            current = based_on.get(current)
        else:
            resolved.setdefault(style_id, False)
    return resolved
