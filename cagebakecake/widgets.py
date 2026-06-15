"""Reusable themed widgets for the controls dock.

These recreate the design handoff's dock chrome on top of plain Qt widgets (styled
by theme.build_qss): collapsible sections with a clickable header, matching the
"Shape the Cage / Name match / Recipe" grouping. Kept apart from window.py so the
window stays a thin assembly layer.
"""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_BADGE = {"matched": "matched", "no match": "nomatch", "manual": "manual"}


class CollapsibleSection(QWidget):
    """A titled, collapsible group: a header button toggles a QFormLayout body.

    Add rows with ``section.form().addRow(...)`` exactly like a QFormLayout, so the
    existing label+control rows port over unchanged. The header carries the
    ``sectionHeader`` object name for QSS styling.
    """

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._btn = QToolButton()
        self._btn.setObjectName("sectionHeader")
        self._btn.setText(title)
        self._btn.setCheckable(True)
        self._btn.setChecked(True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.DownArrow)
        self._btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn.clicked.connect(self._on_toggle)

        self._body = QWidget()
        self._form = QFormLayout(self._body)
        self._form.setContentsMargins(10, 8, 8, 10)
        self._form.setSpacing(8)
        self._form.setLabelAlignment(Qt.AlignLeft)
        self._form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._btn)
        lay.addWidget(self._body)

    def form(self) -> QFormLayout:
        return self._form

    def set_expanded(self, expanded: bool) -> None:
        self._btn.setChecked(expanded)
        self._on_toggle(expanded)

    def _on_toggle(self, checked: bool) -> None:
        self._body.setVisible(checked)
        self._btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)


class _HoverRow(QFrame):
    """One name-match row: editable LP/HP names, a status glyph and badge. Entering
    the row highlights the corresponding part(s) in the viewport (via on_enter) and
    leaving clears it (on_leave)."""

    def __init__(self, on_enter, on_leave, parent=None):
        super().__init__(parent)
        self.setObjectName("nmRow")
        self._on_enter = on_enter
        self._on_leave = on_leave

    def enterEvent(self, event):
        self._on_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._on_leave()
        super().leaveEvent(event)


class NameMatchTable(QWidget):
    """The design's name-match table: one row per low/high part pair, with editable
    names, a live matched / no-match / manual status, and hover-to-highlight.

    It is editor-driven: `editor_getter()` returns the current CageEditor (which is
    recreated when a new mesh opens), `rebuild()` repopulates from editor.name_pairs(),
    editing a name calls editor.rename_part, and hovering a row calls
    editor.highlight_parts / clear_part_highlight plus an optional on_hover(label|None).
    """

    def __init__(self, editor_getter, on_hover=None, parent=None):
        super().__init__(parent)
        self._editor_getter = editor_getter
        self._on_hover = on_hover or (lambda _label: None)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

        header = QFrame()
        hl = QGridLayout(header)
        hl.setContentsMargins(8, 4, 8, 4)
        low = QLabel("LOW POLY")
        high = QLabel("HIGH POLY")
        low.setObjectName("eyebrow")
        high.setObjectName("eyebrow")
        hl.addWidget(low, 0, 0)
        hl.addWidget(high, 0, 2)
        hl.setColumnStretch(0, 1)
        hl.setColumnStretch(2, 1)
        self._lay.addWidget(header)

        self._rows = QWidget()
        self._rows_lay = QVBoxLayout(self._rows)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(0)
        self._lay.addWidget(self._rows)

    def rebuild(self) -> None:
        """Clear and repopulate rows from the current editor's name pairs."""
        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        editor = self._editor_getter()
        if editor is None:
            return
        for row in editor.name_pairs():
            self._rows_lay.addWidget(self._make_row(row))

    def _make_row(self, row: dict) -> QWidget:
        editor = self._editor_getter()
        parts = []
        if row["low"] is not None:
            parts.append(("low", row["low"]))
        if row["high"] is not None:
            parts.append(("high", row["high"]))
        label = row["low_name"] or row["high_name"] or ""

        def on_enter():
            editor.highlight_parts(parts)
            self._on_hover(label)

        def on_leave():
            editor.clear_part_highlight()
            self._on_hover(None)

        frame = _HoverRow(on_enter, on_leave)
        grid = QGridLayout(frame)
        grid.setContentsMargins(8, 6, 8, 6)

        lp = QLineEdit(row["low_name"] or "")
        lp.setEnabled(row["low"] is not None)
        if row["low"] is not None:
            lp.editingFinished.connect(
                lambda e=lp, i=row["low"]: self._rename("low", i, e.text()))
        glyph = QLabel("<->")
        glyph.setProperty("glyph", _BADGE[row["status"]])
        glyph.setAlignment(Qt.AlignCenter)
        hp = QLineEdit(row["high_name"] or "")
        hp.setEnabled(row["high"] is not None)
        if row["high"] is not None:
            hp.editingFinished.connect(
                lambda e=hp, i=row["high"]: self._rename("high", i, e.text()))
        badge = QLabel(row["status"])
        badge.setProperty("badge", _BADGE[row["status"]])
        badge.setAlignment(Qt.AlignCenter)

        grid.addWidget(lp, 0, 0)
        grid.addWidget(glyph, 0, 1)
        grid.addWidget(hp, 0, 2)
        grid.addWidget(badge, 0, 3)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        return frame

    def _rename(self, group: str, idx: int, name: str) -> None:
        editor = self._editor_getter()
        if editor is not None:
            editor.rename_part(group, idx, name)
            self.rebuild()  # re-derive match status live
