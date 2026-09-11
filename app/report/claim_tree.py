"""
The claim-tree drawing for section I.

Trees are drawn the way the reference report draws them: each independent claim sits at
the top of its tree as an ellipse, its dependants hang in a row beneath it, and an arrow
runs from each dependant up to the claim it depends from -- the arrow points the way the
dependency reads, "claim 2 depends on claim 1".  Trees are laid out side by side across
the page and wrap to a new row when they run out of width, so a twenty-claim set with
three independent claims fits on one band.

Each node says three things at a glance:

* outline colour -- the claim's statutory type (the legend names the colours);
* grey fill -- the claim is independent;
* dotted outline -- the claim's parent reference is invalid, so the branch it is drawn on
  is the *reported* structure, not one the numbering actually supports.

Node width is driven by the longest label but floored, and the horizontal gap collapses
before anything else, because the readable limit is the claim number inside the ellipse:
squeezing the gap keeps a wide set on one row, squeezing the ellipse does not.
"""
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable

from app.analysis.hierarchy.models import ClaimNode

NODE_HEIGHT = 17.0
NODE_MIN_WIDTH = 24.0
NODE_PADDING = 10.0
LEAF_GAP_MAX = 8.0
LEAF_GAP_MIN = 1.5
LEVEL_HEIGHT = 46.0
TREE_GAP_MAX = 18.0
TREE_GAP_MIN = 8.0
ROW_GAP = 24.0

FONT_NAME = "Helvetica"
FONT_SIZE = 8.0

_INDEPENDENT_FILL = colors.HexColor("#C9C9C9")
_DEPENDENT_FILL = colors.white
_ARROW_COLOR = colors.HexColor("#333333")
_TEXT_COLOR = colors.HexColor("#1A1A1A")
_ARROW_HEAD = 3.4


class _Node:
    """A laid-out node: its own box plus the subtree width it needs."""

    def __init__(self, number: int, label: str):
        self.number = number
        self.label = label
        self.width = max(NODE_MIN_WIDTH, stringWidth(label, FONT_NAME, FONT_SIZE) + NODE_PADDING)
        self.children: List["_Node"] = []
        self.x = 0.0           # centre
        self.y = 0.0           # centre, measured downwards from the top of the drawing
        self.span = self.width

    def measure(self, gap: float) -> float:
        """Width this subtree needs, children laid side by side."""
        if not self.children:
            self.span = self.width
            return self.span
        children_span = sum(child.measure(gap) for child in self.children)
        children_span += gap * (len(self.children) - 1)
        self.span = max(self.width, children_span)
        return self.span

    def place(self, left: float, depth: int, gap: float) -> None:
        """Assigns centres, children first, so a parent can centre over them."""
        self.y = depth * LEVEL_HEIGHT + NODE_HEIGHT / 2

        if not self.children:
            self.x = left + self.width / 2
            return

        cursor = left
        if self.span > sum(c.span for c in self.children) + gap * (len(self.children) - 1):
            # The parent is wider than its children; centre the children under it.
            children_span = sum(c.span for c in self.children) + gap * (len(self.children) - 1)
            cursor = left + (self.span - children_span) / 2

        for child in self.children:
            child.place(cursor, depth + 1, gap)
            cursor += child.span + gap

        self.x = (self.children[0].x + self.children[-1].x) / 2

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def depth(self) -> int:
        return 1 + max((child.depth() for child in self.children), default=0)


class ClaimForestDrawing(Flowable):
    """Every claim tree in the set, laid out across the page."""

    def __init__(self, nodes: Dict[int, ClaimNode], roots: List[int]):
        super().__init__()
        self.nodes = nodes
        self.roots = roots
        self._trees: List[_Node] = []
        self._rows: List[List[_Node]] = []
        self._gap = LEAF_GAP_MAX
        self._tree_gap = TREE_GAP_MAX
        self._width = 0.0
        self._height = 0.0

    # -- reportlab protocol -------------------------------------------------

    def wrap(self, available_width: float, available_height: float):
        self._build(available_width)
        return self._width, self._height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFont(FONT_NAME, FONT_SIZE)

        for tree in self._trees:
            for node in tree.walk():
                for child in node.children:
                    self._draw_arrow(canvas, child, node)
        for tree in self._trees:
            for node in tree.walk():
                self._draw_node(canvas, node)

        canvas.restoreState()

    # -- layout -------------------------------------------------------------

    def _build(self, available_width: float) -> None:
        if self._trees:
            return

        self._trees = [self._build_tree(root, set()) for root in self.roots]

        # Shrink the gaps before wrapping: a claim set reads as one picture when its trees
        # sit side by side, so the space between nodes and then between trees gives way
        # first, and only then does a row break.  The last attempt stands if none fits.
        attempts = [(gap, TREE_GAP_MAX) for gap in (LEAF_GAP_MAX, 6.0, 4.0)]
        attempts += [(gap, TREE_GAP_MIN) for gap in (4.0, 2.5, LEAF_GAP_MIN)]
        for gap, tree_gap in attempts:
            self._gap, self._tree_gap = gap, tree_gap
            spans = [tree.measure(gap) for tree in self._trees]
            if sum(spans) + tree_gap * (len(spans) - 1) <= available_width:
                break

        self._rows = self._pack_rows(available_width)

        top = 0.0
        width = 0.0
        for row in self._rows:
            left = 0.0
            row_depth = 0
            for tree in row:
                tree.place(left, 0, self._gap)
                for node in tree.walk():
                    node.y += top
                row_depth = max(row_depth, tree.depth())
                left += tree.span + self._tree_gap
            width = max(width, left - self._tree_gap)
            top += row_depth * LEVEL_HEIGHT + ROW_GAP

        self._width = width
        self._height = max(top - ROW_GAP, NODE_HEIGHT)

        # Flip to reportlab's bottom-left origin.
        for tree in self._trees:
            for node in tree.walk():
                node.y = self._height - node.y

    def _build_tree(self, number: int, seen: set) -> _Node:
        source = self.nodes.get(number)
        node = _Node(number, source.display if source else str(number))
        seen.add(number)

        for child_number in (source.children if source else []):
            # A multiple dependent claim hangs under each of its parents, but never
            # twice in the same tree.
            if child_number in seen:
                continue
            node.children.append(self._build_tree(child_number, seen))

        return node

    def _pack_rows(self, available_width: float) -> List[List[_Node]]:
        rows: List[List[_Node]] = []
        current: List[_Node] = []
        used = 0.0

        for tree in self._trees:
            needed = tree.span + (self._tree_gap if current else 0)
            if current and used + needed > available_width:
                rows.append(current)
                current, used = [tree], tree.span
            else:
                current.append(tree)
                used += needed

        if current:
            rows.append(current)
        return rows

    # -- painting -----------------------------------------------------------

    def _draw_node(self, canvas, node: _Node) -> None:
        source = self.nodes.get(node.number)
        outline = colors.HexColor(source.category.color if source else "#999999")
        fill = _INDEPENDENT_FILL if (source and source.is_independent) else _DEPENDENT_FILL

        canvas.setFillColor(fill)
        canvas.setStrokeColor(outline)
        canvas.setLineWidth(0.9)
        if source and source.has_invalid_parent:
            canvas.setDash(1.8, 1.8)

        canvas.ellipse(
            node.x - node.width / 2, node.y - NODE_HEIGHT / 2,
            node.x + node.width / 2, node.y + NODE_HEIGHT / 2,
            stroke=1, fill=1,
        )
        canvas.setDash()

        canvas.setFillColor(_TEXT_COLOR)
        canvas.setFont(FONT_NAME, FONT_SIZE)
        canvas.drawCentredString(node.x, node.y - FONT_SIZE / 2 + 0.8, node.label)

    def _draw_arrow(self, canvas, child: _Node, parent: _Node) -> None:
        """An arrow from the dependent claim up to the claim it depends from."""
        start_x, start_y = child.x, child.y + NODE_HEIGHT / 2
        end_x, end_y = parent.x, parent.y - NODE_HEIGHT / 2

        canvas.setStrokeColor(_ARROW_COLOR)
        canvas.setFillColor(_ARROW_COLOR)
        canvas.setLineWidth(0.5)
        canvas.line(start_x, start_y, end_x, end_y)

        # Arrowhead at the parent, pointing along the line.
        dx, dy = end_x - start_x, end_y - start_y
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux, uy = dx / length, dy / length
        base_x, base_y = end_x - ux * _ARROW_HEAD, end_y - uy * _ARROW_HEAD
        path = canvas.beginPath()
        path.moveTo(end_x, end_y)
        path.lineTo(base_x - uy * _ARROW_HEAD / 2, base_y + ux * _ARROW_HEAD / 2)
        path.lineTo(base_x + uy * _ARROW_HEAD / 2, base_y - ux * _ARROW_HEAD / 2)
        path.close()
        canvas.drawPath(path, stroke=0, fill=1)


def build_forest(hierarchy) -> Optional[ClaimForestDrawing]:
    """The drawing for a :class:`HierarchyResult`, or None when there is nothing to draw."""
    if not hierarchy or not hierarchy.trees:
        return None
    return ClaimForestDrawing(hierarchy.nodes, [tree.root for tree in hierarchy.trees])
