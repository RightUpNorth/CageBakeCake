"""Reusable themed widgets for the controls dock.

These recreate the design handoff's dock chrome on top of plain Qt widgets (styled
by theme.build_qss): collapsible sections with a clickable header, matching the
"Shape the Cage / Name match / Recipe" grouping. Kept apart from window.py so the
window stays a thin assembly layer.
"""

from __future__ import annotations

from qtpy.QtCore import QSize, Qt, Signal
from qtpy.QtGui import QColor, QPainter
from qtpy.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import recipe, theme


class SegmentedControl(QWidget):
    """A pill segmented control - a row of exclusive checkable buttons, matching the
    design's Direction/Mood toggles. Emits changed(index) on selection."""

    changed = Signal(int)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = []
        for i, text in enumerate(options):
            b = QToolButton()
            b.setObjectName("segment")
            b.setText(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self._group.addButton(b, i)
            lay.addWidget(b)
            self._buttons.append(b)
        self._buttons[0].setChecked(True)
        self._group.idClicked.connect(self.changed.emit)

    def set_current_index(self, i: int) -> None:
        self._buttons[i].setChecked(True)

    def current_index(self) -> int:
        return self._group.checkedId()


def eyebrow_chip(number: str, text: str, kind: str = "accent") -> QWidget:
    """A numbered eyebrow row: a small colored number chip + an uppercase label,
    matching the design's '1 BAKE SETTINGS' (amber) / '2 PACKING' (accent) headers.
    `kind` is 'accent' or 'accent2'; the chip recolors with the theme via QSS."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 4, 0, 2)
    lay.setSpacing(7)
    chip = QLabel(number)
    chip.setObjectName("numAccent2" if kind == "accent2" else "numAccent")
    chip.setAlignment(Qt.AlignCenter)
    chip.setFixedSize(16, 16)
    label = QLabel(text)
    label.setObjectName("eyebrow")
    lay.addWidget(chip)
    lay.addWidget(label)
    lay.addStretch(1)
    return row


def channel_chip(letter: str) -> QLabel:
    """An 18px channel-letter chip (R/G/B/A) in the fixed channel color."""
    lbl = QLabel(letter)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setFixedSize(18, 18)
    color = theme.CHANNEL_COLORS[letter.lower()]
    lbl.setStyleSheet(
        f"background:{color};color:#fff;border-radius:5px;font-size:10px;font-weight:700;")
    return lbl


class ToggleSwitch(QCheckBox):
    """A pill switch matching the design's toggles. Subclasses QCheckBox so it keeps
    the full checkbox API (toggled, setChecked, ...) and just paints a 36x20 track with
    a sliding 16px knob plus the label. Colors come from the active palette, so it
    recolors with the theme on the next repaint."""

    _TRACK_W = 36
    _TRACK_H = 20
    _KNOB = 16

    def sizeHint(self) -> QSize:
        if not self.text():  # pill only - used at the right edge of a labeled row
            return QSize(self._TRACK_W + 4, self._TRACK_H + 4)
        base = super().sizeHint()
        return QSize(base.width() + self._TRACK_W + 6, max(base.height(), self._TRACK_H + 2))

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)  # whole row toggles, like the design

    def paintEvent(self, _event) -> None:
        p = theme.active()
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - self._TRACK_H) // 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(p["accent"] if on else p["inset"]))
        painter.drawRoundedRect(0, y, self._TRACK_W, self._TRACK_H,
                                self._TRACK_H / 2, self._TRACK_H / 2)
        painter.setBrush(QColor("#ffffff"))
        knob_x = (self._TRACK_W - self._KNOB - 2) if on else 2
        painter.drawEllipse(knob_x, y + 2, self._KNOB, self._KNOB)

        painter.setPen(QColor(p["ink"]))
        text_x = self._TRACK_W + 8
        painter.drawText(text_x, 0, self.width() - text_x, self.height(),
                         Qt.AlignVCenter | Qt.AlignLeft, self.text())

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


def _swatch(kind: str) -> QLabel:
    """A 20px rounded type swatch carrying the kind's short tag (N, AO, ...), in the
    fixed (non-themed) bake-map swatch color."""
    lbl = QLabel(theme.MAP_TAGS[kind])
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setFixedSize(22, 22)
    lbl.setStyleSheet(
        f"background:{theme.MAP_SWATCHES[kind]};color:#fff;border-radius:6px;"
        "font-size:9px;font-weight:700;")
    return lbl


class RecipePanel(QWidget):
    """The design's Recipe section: a preset selector + export, the editable list of
    maps to bake, and the channel-packing output cards. Edits mutate a recipe.Recipe
    in place and call on_change(recipe) so the window can update the primary button and
    the saved/unsaved state. {LP} previews use get_lp_name()."""

    def __init__(self, get_lp_name, on_change=None, parent=None):
        super().__init__(parent)
        self._get_lp_name = get_lp_name
        self._on_change = on_change or (lambda _r: None)
        self._recipe = recipe.presets()["Game-ready"]
        self._presets = recipe.presets()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # Header: preset selector + export.
        head = QHBoxLayout()
        self._preset = QComboBox()
        self._preset.addItems(list(self._presets))
        self._preset.currentTextChanged.connect(self._on_preset)
        export = QToolButton()
        export.setText("...")
        export.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(export)
        menu.addAction("Export recipe (.json)...", self._export)
        menu.addAction("Load recipe (.json)...", self._load)
        export.setMenu(menu)
        head.addWidget(QLabel("Preset"))
        head.addWidget(self._preset, 1)
        head.addWidget(export)
        lay.addLayout(head)

        # Maps to bake.
        maps_head = QHBoxLayout()
        eb = QLabel("MAPS TO BAKE")
        eb.setObjectName("eyebrow")
        add = QToolButton()
        add.setText("+ Add")
        add.setPopupMode(QToolButton.InstantPopup)
        add_menu = QMenu(add)
        for kind in theme.MAP_LABELS:
            tag = "RGB" if kind in theme.RGB_KINDS else "grey"
            act = add_menu.addAction(f"{theme.MAP_LABELS[kind]}  ({tag})")
            act.triggered.connect(lambda _checked=False, k=kind: self._add_map(k))
        add.setMenu(add_menu)
        maps_head.addWidget(eb)
        maps_head.addStretch(1)
        maps_head.addWidget(add)
        lay.addLayout(maps_head)
        self._maps_box = QVBoxLayout()
        self._maps_box.setSpacing(4)
        lay.addLayout(self._maps_box)

        # Packing - the design's numbered "2 PACKING" section.
        lay.addWidget(eyebrow_chip("2", "PACKING", "accent"))
        pack_head = QHBoxLayout()
        pack_head.addStretch(1)
        add_color = QPushButton("+ Color map")
        add_color.clicked.connect(lambda: self._add_output("color"))
        add_packed = QPushButton("+ Packed map")
        add_packed.clicked.connect(lambda: self._add_output("packed"))
        pack_head.addWidget(add_color)
        pack_head.addWidget(add_packed)
        lay.addLayout(pack_head)
        self._pack_box = QVBoxLayout()
        self._pack_box.setSpacing(6)
        lay.addLayout(self._pack_box)

        self.rebuild()

    # --- state -----------------------------------------------------------
    def recipe(self):
        return self._recipe

    def _changed(self) -> None:
        self._on_change(self._recipe)

    def _on_preset(self, name: str) -> None:
        if name in self._presets:
            # fresh copy so editing one preset never mutates the stored template
            self._recipe = recipe.presets()[name]
            self.rebuild()
            self._changed()

    # --- rebuild ---------------------------------------------------------
    def rebuild(self) -> None:
        _clear(self._maps_box)
        for m in self._recipe.bake_maps:
            self._maps_box.addWidget(self._map_row(m))
        _clear(self._pack_box)
        for o in self._recipe.outputs:
            self._pack_box.addWidget(self._output_card(o))

    def _map_row(self, m) -> QWidget:
        row = QFrame()
        row.setObjectName("card")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        h.addWidget(_swatch(m.kind))
        name = QLineEdit(m.name)
        name.editingFinished.connect(lambda e=name, mm=m: self._rename_map(mm, e.text()))
        h.addWidget(name, 1)
        if m.kind == "normal":
            space = QComboBox()
            space.addItems(["tangent", "object"])
            space.setCurrentText(m.space or "tangent")
            space.currentTextChanged.connect(lambda t, mm=m: self._set_space(mm, t))
            h.addWidget(space)
        pill = QLabel(theme.MAP_LABELS[m.kind])
        pill.setObjectName("kindpill")
        h.addWidget(pill)
        rm = QToolButton()
        rm.setText("x")
        rm.clicked.connect(lambda _c=False, mm=m: self._remove_map(mm))
        h.addWidget(rm)
        return row

    def _output_card(self, o) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(8, 6, 8, 8)

        top = QHBoxLayout()
        fname = QLineEdit(o.file)
        fname.editingFinished.connect(lambda e=fname, oo=o: self._rename_output(oo, e.text()))
        top.addWidget(fname, 1)
        top.addWidget(QLabel(".png"))
        kind = QLabel("Color" if o.type == "color" else "Packed")
        kind.setObjectName("eyebrow")
        top.addWidget(kind)
        rm = QToolButton()
        rm.setText("x")
        rm.clicked.connect(lambda _c=False, oo=o: self._remove_output(oo))
        top.addWidget(rm)
        v.addLayout(top)

        resolved = QLabel("-> " + recipe.resolve_filename(o.file, self._get_lp_name()))
        resolved.setObjectName("resolved")
        v.addWidget(resolved)

        cells = QHBoxLayout()
        if o.type == "color":
            cells.addWidget(self._cell(o, "r", "RGB", rgb=True), 2)
            cells.addWidget(self._cell(o, "a", "A", rgb=False), 1)
        else:
            for c in ("r", "g", "b", "a"):
                cells.addWidget(self._cell(o, c, c.upper(), rgb=False), 1)
        v.addLayout(cells)
        return card

    def _cell(self, o, channel: str, letter: str, rgb: bool) -> QWidget:
        """A channel-assignment cell: colored channel-letter chip(s) + a flat button that
        shows the assigned map name (or -) and opens a menu of compatible maps (3-channel
        for the RGB cell, 1-channel otherwise)."""
        want = 3 if rgb else 1
        current = self._recipe.map_by_id(o.ch.get(channel))
        cell = QFrame()
        cell.setObjectName("cell")
        h = QHBoxLayout(cell)
        h.setContentsMargins(5, 4, 6, 4)
        h.setSpacing(4)
        for letter_chip in (("R", "G", "B") if rgb else (letter,)):
            h.addWidget(channel_chip(letter_chip))
        btn = QToolButton()
        btn.setObjectName("cellbtn")
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setText(current.name if current else "-")
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        menu = QMenu(btn)
        none_act = menu.addAction("None (empty)")
        none_act.triggered.connect(lambda _c=False: self._assign(o, channel, None))
        for m in self._recipe.bake_maps:
            if m.channels == want:
                act = menu.addAction(m.name)
                act.triggered.connect(lambda _c=False, mid=m.id: self._assign(o, channel, mid))
        btn.setMenu(menu)
        h.addWidget(btn, 1)
        return cell

    # --- edits -----------------------------------------------------------
    def _add_map(self, kind: str) -> None:
        self._recipe.add_map(kind)
        self.rebuild()
        self._changed()

    def _remove_map(self, m) -> None:
        self._recipe.remove_map(m.id)
        self.rebuild()
        self._changed()

    def _rename_map(self, m, name: str) -> None:
        if name and name != m.name:
            m.name = self._recipe.unique_name(name) if name in {
                x.name for x in self._recipe.bake_maps if x is not m} else name
            self.rebuild()  # refresh packing cell labels
            self._changed()

    def _set_space(self, m, space: str) -> None:
        m.space = space
        self._changed()

    def _add_output(self, kind: str) -> None:
        if kind == "color":
            out = recipe._color("{LP}_map", None)
        else:
            out = recipe._packed("{LP}_map")
        self._recipe.outputs.append(out)
        self.rebuild()
        self._changed()

    def _remove_output(self, o) -> None:
        self._recipe.outputs = [x for x in self._recipe.outputs if x is not o]
        self.rebuild()
        self._changed()

    def _rename_output(self, o, name: str) -> None:
        if name and name != o.file:
            o.file = name
            self.rebuild()  # refresh the resolved preview
            self._changed()

    def _assign(self, o, channel: str, map_id) -> None:
        if o.type == "color" and channel == "r":
            o.ch["r"] = o.ch["g"] = o.ch["b"] = map_id  # RGB mirrors r
        else:
            o.ch[channel] = map_id
        self.rebuild()
        self._changed()

    # --- json ------------------------------------------------------------
    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export recipe", "", "JSON (*.json)")
        if path:
            self._recipe.save(path)

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load recipe", "", "JSON (*.json)")
        if path:
            self._recipe = recipe.Recipe.load(path)
            self.rebuild()
            self._changed()


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
