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
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


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
