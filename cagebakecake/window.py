"""Qt front end: a real application window around the CageEditor viewport.

The interaction logic (pick a cage vertex, drag the gizmo, shift-drag the lighting,
bake) all lives in app.CageEditor and is format/UI-blind. This module is a thin Qt
shell: it embeds a pyvistaqt.QtInteractor as the render surface, drives the editor's
sliders/toggles from dock widgets and a menu bar, and rebuilds the editor when the
user opens different meshes. The standalone pyvista.Plotter path (app.run) is still
the headless / screenshot route and is unaffected.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from pyvistaqt import QtInteractor
from qtpy.QtCore import QObject, QPoint, Qt, QSettings, QThread, Signal
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import bake, chrome, project, recipe, theme, uvlayout, win_chrome
from .app import CageEditor
from .imageview import ImageView
from .widgets import (
    CollapsibleSection,
    NameMatchTable,
    RecipePanel,
    SegmentedControl,
    ToggleSwitch,
    channel_chip,
    eyebrow_chip,
)

_USD_FILTER = "USD (*.usd *.usdc *.usda);;All files (*)"
_PROJECT_FILTER = "CageBakeCake project (*.cbcproj);;All files (*)"
_SLIDER_STEPS = 1000  # integer resolution for the float-valued sliders
_EXPLODE_MAX = 2.0    # max exploded-bake separation factor (slider top)
_BAKE_SIZES = [256, 512, 1024, 2048, 4096, 8192, 16384]  # normal-map width/height choices


class _BakeWorker(QObject):
    """Runs a pure-compute bake closure on a worker thread and reports back via signals.

    `compute(emit)` is called on the thread - it must be pure (no Qt/VTK), taking a
    progress callback. Its return value (or an exception) is delivered on `finished`,
    handled on the main thread where the VTK/actor updates are safe."""

    progress = Signal(str)
    finished = Signal(object)

    def __init__(self, compute):
        super().__init__()
        self._compute = compute

    def run(self) -> None:
        try:
            result = self._compute(self.progress.emit)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
            result = exc
        self.finished.emit(result)


class MainWindow(QMainWindow):
    """Top-level window: menu bar + viewport + a controls dock on the right."""

    def __init__(
        self,
        low_path: str,
        high_path: str | None = None,
        cage_path: str | None = None,
        hdr_path: str | None = None,
        global_push: float | None = None,
    ):
        super().__init__()
        self.setWindowTitle("CageBakeCake")
        self.resize(1340, 856)  # design max content size
        self.setMinimumSize(900, 600)

        self._low_path = low_path
        self._high_path = high_path
        self._cage_path = cage_path
        self._hdr_path = hdr_path
        self._global_push = global_push

        self._interactor: QtInteractor | None = None
        self.editor: CageEditor | None = None
        self._cancel = False  # set by the Cancel button, polled by the bake loops
        # Threaded bake state: the worker keeps the UI live during a ray cast.
        self._bake_busy = False
        self._bake_thread: QThread | None = None
        self._bake_worker: _BakeWorker | None = None
        self._closing = False
        # A saved editor state staged by Open Project, applied to the fresh editor the
        # next _rebuild creates (and then cleared). None on a plain mesh open.
        self._pending_editor_state: dict | None = None
        self._project_path: str | None = None
        # Recent files (QSettings-backed) + the clean cage-edit baseline for the
        # unsaved-edits quit guard. Drag-and-drop opens meshes / projects.
        self._settings = QSettings("CageBakeCake", "CageBakeCake")
        self._saved_edits: dict | None = None
        self.setAcceptDrops(True)
        self._title_bar: QWidget | None = None
        self._native_chrome = False  # win32 native frameless (Aero Snap kept)

        # Theme axes (direction + mood) drive the 6-palette matrix; see theme.py.
        self._direction = theme.DEFAULT_DIRECTION
        self._mood = theme.DEFAULT_MOOD

        # Go frameless so the design's single 48px themed title bar is the real one.
        # On win32 we keep the native window (resize/snap/shadow) and only strip the
        # title bar via WM_NCCALCSIZE; elsewhere we use FramelessWindowHint + grips.
        if sys.platform != "win32":
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

        self._build_chrome()  # title bar (48px) + menu bar (36px) at the very top
        self._build_dock()
        self._build_central()
        self._build_statusbar()
        self._rebuild()
        self._apply_theme()
        self._enable_frameless()

    # --- construction -------------------------------------------------------
    def _build_chrome(self) -> None:
        """Stack the title bar (48px) above the menu bar (36px) in a single widget set
        as the window's menu widget, so both span the full width above the dock - the
        design's top-level order (title bar, then menu bar)."""
        top = QWidget()
        top.setObjectName("chrome")
        lay = QVBoxLayout(top)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_titlebar())
        lay.addWidget(self._build_menu())
        self.setMenuWidget(top)

    def _build_titlebar(self) -> QWidget:
        """The design's 48px title bar: app mark (cake) + title + asset name on the
        left; the viewport-mode dropdown, the Direction/Mood toggles, and three
        functional window buttons (minimize / maximize / close) on the right. The bar
        itself is a DragBar so dragging it moves the (frameless) window."""
        bar = chrome.DragBar(self)
        bar.setObjectName("titlebar")
        bar.setFixedHeight(48)
        self._title_bar = bar
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 0, 10, 0)
        h.setSpacing(8)

        mark = QLabel()
        mark.setObjectName("appmark")
        mark.setFixedSize(24, 24)
        mark.setAlignment(Qt.AlignCenter)
        self._appmark = mark
        self._paint_appmark()
        title = QLabel("CageBakeCake")
        title.setObjectName("apptitle")
        self._asset_label = QLabel("")
        self._asset_label.setObjectName("assetname")
        h.addWidget(mark)
        h.addWidget(title)
        h.addWidget(self._asset_label)
        h.addStretch(1)

        self._viewport_mode = QComboBox()
        self._viewport_mode.addItems(["3D", "3D + 2D", "2D"])
        self._viewport_mode.setCurrentText("3D + 2D")
        self._viewport_mode.currentTextChanged.connect(lambda _t: self._apply_viewport_mode())
        h.addWidget(self._viewport_mode)

        theme_label = QLabel("THEME")
        theme_label.setObjectName("themelabel")
        h.addWidget(theme_label)
        self._direction_pick = SegmentedControl(["Patisserie", "Chocolatier"])  # A, B
        self._direction_pick.changed.connect(self._on_direction)
        h.addWidget(self._direction_pick)
        self._mood_pick = SegmentedControl(["Light", "Neutral", "Dark"])
        self._mood_pick.changed.connect(self._on_mood)
        h.addWidget(self._mood_pick)

        # Three functional window buttons (the design's faux dots, made real).
        dots = QWidget()
        dots.setObjectName("windots")  # transparent so the title bar shows behind
        dlay = QHBoxLayout(dots)
        dlay.setContentsMargins(8, 0, 0, 0)
        dlay.setSpacing(7)
        for name, slot in (("winmin", self.showMinimized),
                           ("winmax", self._toggle_max),
                           ("winclose", self.close)):
            d = QToolButton()
            d.setObjectName(name)
            d.setFixedSize(13, 13)
            d.setCursor(Qt.PointingHandCursor)
            d.clicked.connect(slot)
            dlay.addWidget(d)
        h.addWidget(dots)
        return bar

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _paint_appmark(self) -> None:
        """(Re)paint the cake app-mark in the current palette's on-accent ink."""
        ink = theme.active()["accent-ink"]
        self._appmark.setPixmap(chrome.cake_icon(18, ink))

    # --- frameless window plumbing ------------------------------------------
    def _enable_frameless(self) -> None:
        """Apply native borderless chrome on win32 (keeps Aero Snap/resize/shadow);
        fall back to portable Qt resize grips if that fails or off-Windows."""
        if sys.platform == "win32":
            # Set the flag *before* enable(): its frame-change triggers the
            # WM_NCCALCSIZE that nativeEvent must handle to strip the title bar.
            self._native_chrome = True
            if win_chrome.enable(self):
                return
            self._native_chrome = False
            # native path failed: become frameless the portable way instead
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        chrome.install_resize_grips(self)

    def nativeEvent(self, event_type, message):
        """Forward non-client messages to the win32 chrome so the borderless window
        still resizes/snaps/drags natively."""
        if self._native_chrome and bytes(event_type) == b"windows_generic_MSG":
            result = win_chrome.handle(self, message, self._is_caption)
            if result is not None:
                return result
        return super().nativeEvent(event_type, message)

    def _is_caption(self, x: float, y: float) -> bool:
        """Is the window-local point (device-independent px) in the draggable title-bar
        region? True over empty bar/labels, False over the controls so they stay
        clickable."""
        tb = self._title_bar
        if tb is None:
            return False
        origin = tb.mapTo(self, QPoint(0, 0))
        local = QPoint(int(x) - origin.x(), int(y) - origin.y())
        if not tb.rect().contains(local):
            return False
        child = tb.childAt(local)
        return child is None or isinstance(child, QLabel)

    def _build_menu(self) -> QMenuBar:
        bar = QMenuBar()
        bar.setFixedHeight(36)

        file_menu = bar.addMenu("&File")
        file_menu.addAction("Open Low Poly...", self._open_low)
        file_menu.addAction("Open High Poly...", self._open_high)
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction("Open Project...", self._open_project)
        file_menu.addAction("Save Project As...", self._save_project)
        file_menu.addSeparator()
        file_menu.addAction("Save Cage As...", self._save_cage)
        file_menu.addAction("Export Normal Map...", self._export)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        # Menu toggles flip the matching dock checkbox so the two stay in sync.
        view_menu = bar.addMenu("&View")
        view_menu.addAction("Toggle High Poly Visible", lambda: self._high_visible.toggle())
        view_menu.addAction("Low Poly Shaded", lambda: self._low_shaded.toggle())
        view_menu.addAction("Low Poly Wireframe", lambda: self._low_wire.toggle())
        view_menu.addAction("High Poly Shaded", lambda: self._high_shaded.toggle())
        view_menu.addAction("High Poly Wireframe", lambda: self._high_wire.toggle())
        view_menu.addAction("Toggle Normal Map", lambda: self._normal_map.toggle())
        view_menu.addAction("Toggle LP Normals", lambda: self._show_normals.toggle())
        view_menu.addAction("Toggle Ray-miss Overlay", lambda: self._miss_overlay.toggle())
        view_menu.addSeparator()
        view_menu.addAction("Toggle Cage Points", lambda: self._cage_points.toggle())
        view_menu.addAction("Toggle Cage Wireframe", lambda: self._cage_wire.toggle())
        view_menu.addSeparator()
        view_menu.addAction("Reset Cage", self._reset_cage)
        view_menu.addAction("Reset Selected Point", self._reset_point)

        cage_menu = bar.addMenu("&Cage")
        cage_menu.addAction("Reset Cage", self._reset_cage)
        cage_menu.addAction("Reset Selected Point", self._reset_point)
        cage_menu.addSeparator()
        cage_menu.addAction("Save Cage As...", self._save_cage)

        bake_menu = bar.addMenu("&Bake")
        bake_menu.addAction("Bake recipe", self._bake_recipe)
        bake_menu.addSeparator()
        bake_menu.addAction("Bake normal map", self._bake)
        bake_menu.addAction("Re-bake changed region", self._rebake)
        bake_menu.addAction("Bake AO", self._bake_ao)
        bake_menu.addAction("Bake curvature", self._bake_curvature)
        bake_menu.addAction("Bake height", self._bake_height)
        bake_menu.addAction("Bake position", self._bake_position)
        bake_menu.addAction("Cancel bake", self._cancel_bake)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction("Keyboard shortcuts", lambda: self._set_status(
            "B bake recipe  ·  O soft-select  ·  Z undo  ·  see docs/ for the full list"))

        # The faint caption the design floats at the right of the menu bar.
        caption = QLabel("USD · PySide6 · headless math  ")
        caption.setObjectName("caption")
        bar.setCornerWidget(caption, Qt.TopRightCorner)
        return bar

    def _build_dock(self) -> None:
        """The controls dock, grouped into the design's sections (Shape the Cage /
        Name match / Recipe) inside a scroll area, with a pinned Actions footer. The
        widgets and their editor callbacks are unchanged from the old flat form - only
        their grouping and the primary 'Bake recipe' action are new."""
        dock = QDockWidget("Controls", self)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

        container = QWidget()
        container.setFixedWidth(376)  # design: fixed-width controls dock
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        sections = QVBoxLayout(inner)
        sections.setContentsMargins(10, 8, 10, 8)
        sections.setSpacing(4)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # --- C1 Shape the Cage ------------------------------------------------
        cage_sec = CollapsibleSection("Shape the Cage")
        f = cage_sec.form()
        f.addRow(_helper("The cage is the mold around your asset. Offset presses it out "
                         "from the surface; fix poke-through locally with the gizmo."))
        self._offset = QSlider(Qt.Horizontal)
        self._offset.setRange(0, _SLIDER_STEPS)
        self._offset.valueChanged.connect(self._on_offset)
        self._offset_label = QLabel("-")
        f.addRow(_slider_field("Cage offset", self._offset, self._offset_label))

        self._skew = QSlider(Qt.Horizontal)
        self._skew.setObjectName("amberSlider")  # the design fills Skew with accent2
        self._skew.setRange(0, _SLIDER_STEPS)
        self._skew.valueChanged.connect(self._on_skew)
        self._skew_label = QLabel("-")
        f.addRow(_slider_field("Skew (hard - soft)", self._skew, self._skew_label))

        self._soft = ToggleSwitch("")
        self._soft.toggled.connect(self._on_soft)
        f.addRow(_toggle_row("Soft select (proportional)", self._soft))

        self._radius = QSlider(Qt.Horizontal)
        self._radius.setRange(1, _SLIDER_STEPS)
        self._radius.valueChanged.connect(self._on_radius)
        self._radius_label = QLabel("-")
        f.addRow(_slider_field("Soft radius", self._radius, self._radius_label))

        self._paint_skew = ToggleSwitch("")
        self._paint_skew.toggled.connect(self._on_paint_skew)
        f.addRow(_toggle_row("Paint skew (left-drag)", self._paint_skew))

        self._paint_value = QSlider(Qt.Horizontal)
        self._paint_value.setRange(0, _SLIDER_STEPS)
        self._paint_value.valueChanged.connect(self._on_paint_value)
        self._paint_value_label = QLabel("-")
        f.addRow(_slider_field("Brush skew", self._paint_value, self._paint_value_label))

        # Push/inflate brush + symmetry: paint cage offset directly, optionally mirrored.
        self._push_brush = ToggleSwitch("")
        self._push_brush.toggled.connect(self._on_push_brush)
        f.addRow(_toggle_row("Push brush (left-drag)", self._push_brush))

        self._push_strength = QSlider(Qt.Horizontal)
        self._push_strength.setRange(-_SLIDER_STEPS, _SLIDER_STEPS)
        self._push_strength.valueChanged.connect(self._on_push_strength)
        self._push_strength_label = QLabel("-")
        f.addRow(_slider_field("Brush push (- in / + out)", self._push_strength,
                               self._push_strength_label))

        self._smooth_brush = ToggleSwitch("")
        self._smooth_brush.toggled.connect(self._on_smooth_brush)
        f.addRow(_toggle_row("Smooth brush (left-drag)", self._smooth_brush))

        self._smooth_strength = QSlider(Qt.Horizontal)
        self._smooth_strength.setRange(0, _SLIDER_STEPS)
        self._smooth_strength.valueChanged.connect(self._on_smooth_strength)
        self._smooth_strength_label = QLabel("-")
        f.addRow(_slider_field("Smooth strength", self._smooth_strength,
                               self._smooth_strength_label))

        self._symmetry = SegmentedControl(["Off", "X", "Y", "Z"])
        self._symmetry.changed.connect(self._on_symmetry)
        f.addRow(_toggle_row("Symmetry (mirror edits)", self._symmetry))

        # Precise numeric offset for the selected vertex (follows viewport picks).
        self._vert_offset = QDoubleSpinBox()
        self._vert_offset.setRange(-1.0e6, 1.0e6)
        self._vert_offset.setDecimals(4)
        self._vert_offset.setSingleStep(0.001)
        self._vert_offset.setEnabled(False)
        self._vert_offset.valueChanged.connect(self._on_vert_offset)
        f.addRow("Selected offset", self._vert_offset)
        sections.addWidget(cage_sec)

        # --- Display (interim home; the design moves these to the viewport HUD) ---
        disp_sec = CollapsibleSection("Display")
        f = disp_sec.form()
        self._opacity = QSlider(Qt.Horizontal)
        self._opacity.setRange(0, 100)
        self._opacity.valueChanged.connect(self._on_opacity)
        f.addRow("Cage opacity", self._opacity)
        self._low_shaded = QCheckBox("Low poly shaded")
        self._low_shaded.toggled.connect(lambda v: self.editor.set_low_style(v))
        f.addRow(self._low_shaded)
        self._low_wire = QCheckBox("Low poly wireframe")
        self._low_wire.toggled.connect(lambda v: self.editor.set_low_wire(v))
        f.addRow(self._low_wire)
        self._high_visible = QCheckBox("High poly visible")
        self._high_visible.toggled.connect(lambda v: self.editor.set_high_visible(v))
        f.addRow(self._high_visible)
        self._high_shaded = QCheckBox("High poly shaded")
        self._high_shaded.toggled.connect(lambda v: self.editor.set_high_style(v))
        f.addRow(self._high_shaded)
        self._high_wire = QCheckBox("High poly wireframe")
        self._high_wire.toggled.connect(lambda v: self.editor.set_high_wire(v))
        f.addRow(self._high_wire)
        self._normal_map = QCheckBox("Normal map (shaded low)")
        self._normal_map.toggled.connect(lambda v: self.editor.set_normal_map(v))
        f.addRow(self._normal_map)
        self._show_normals = QCheckBox("Show LP normals")
        self._show_normals.toggled.connect(lambda v: self.editor.set_low_normals(v))
        f.addRow(self._show_normals)
        self._miss_overlay = QCheckBox("Ray-miss overlay (3D)")
        self._miss_overlay.toggled.connect(lambda v: self.editor.set_miss_overlay(v))
        f.addRow(self._miss_overlay)
        self._cage_points = QCheckBox("Cage points")
        self._cage_points.toggled.connect(lambda v: self.editor.set_cage_points(v))
        f.addRow(self._cage_points)
        self._cage_wire = QCheckBox("Cage wireframe")
        self._cage_wire.toggled.connect(lambda v: self.editor.set_cage_wire(v))
        f.addRow(self._cage_wire)
        # Per-part visibility checklist (moved here from Name match; the table below is
        # about pairing, this is about showing/hiding parts).
        self._mesh_list = QListWidget()
        self._mesh_list.setMaximumHeight(120)
        self._mesh_list.itemChanged.connect(self._on_mesh_toggle)
        f.addRow("Meshes", self._mesh_list)
        disp_sec.set_expanded(False)  # collapsed by default; secondary to cage editing
        sections.addWidget(disp_sec)

        # --- C2 Name match ----------------------------------------------------
        nm_sec = CollapsibleSection("Name match")
        f = nm_sec.form()
        self._name_match = ToggleSwitch("")
        self._name_match.toggled.connect(self._on_name_match)
        f.addRow(_toggle_row("Link low/high parts by prim name", self._name_match))
        f.addRow(_helper("Edit a name to fix a pair; hover a row to highlight that "
                         "part in the viewport."))
        self._name_table = NameMatchTable(lambda: self.editor, on_hover=self._on_pair_hover)
        f.addRow(self._name_table)
        sections.addWidget(nm_sec)

        # --- C3 Recipe --------------------------------------------------------
        rec_sec = CollapsibleSection("Recipe")
        f = rec_sec.form()
        f.addRow(_helper("First choose what to bake, then pack those maps into exported "
                         ".png files. Everything here saves with the recipe."))
        # Bake settings (the design's numbered "1 BAKE SETTINGS" / Global card).
        f.addRow(eyebrow_chip("1", "BAKE SETTINGS", "accent2"))
        self._bake_w = self._size_combo()
        self._bake_h = self._size_combo()
        self._bake_w.currentTextChanged.connect(self._on_bake_size)
        self._bake_h.currentTextChanged.connect(self._on_bake_size)
        f.addRow("Bake width", self._bake_w)
        f.addRow("Bake height", self._bake_h)
        self._supersample = QComboBox()
        for s in (1, 2, 4):
            self._supersample.addItem(f"{s}x")
        self._supersample.currentTextChanged.connect(
            lambda t: self.editor.set_supersample(int(t.rstrip("x"))))
        f.addRow("Supersample", self._supersample)
        self._padding = QComboBox()
        for p in (0, 2, 4, 8, 16, 32):
            self._padding.addItem(str(p))
        self._padding.currentTextChanged.connect(lambda t: self.editor.set_padding(int(t)))
        f.addRow("Edge padding", self._padding)
        self._ao_samples = QComboBox()
        for s in (16, 32, 64, 128, 256):
            self._ao_samples.addItem(str(s))
        self._ao_samples.currentTextChanged.connect(lambda t: self.editor.set_ao_samples(int(t)))
        f.addRow("AO samples", self._ao_samples)
        # Exploded bake: separate multi-part low/high so neighbours stop cross-projecting.
        self._explode = QSlider(Qt.Horizontal)
        self._explode.setRange(0, _SLIDER_STEPS)
        self._explode.valueChanged.connect(self._on_explode)
        self._explode_label = QLabel("-")
        f.addRow(_slider_field("Explode bake (0 = in place)", self._explode,
                               self._explode_label))
        self._flip_green = QCheckBox("Flip green (DirectX)")
        self._flip_green.toggled.connect(lambda v: self.editor.set_flip_green(v))
        f.addRow(self._flip_green)
        # Individual (per-type) bakes, kept available alongside the packed recipe bake.
        indiv = QGridLayout()
        for col, (text, slot) in enumerate((
            ("Bake normal", self._bake), ("Re-bake region", self._rebake),
            ("Bake AO", self._bake_ao), ("Bake curvature", self._bake_curvature))):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            indiv.addWidget(btn, 0, col)
        indiv_w = QWidget()
        indiv_w.setLayout(indiv)
        f.addRow("Individual", indiv_w)
        # The recipe editor: preset selector, maps to bake, and channel packing.
        self._recipe_panel = RecipePanel(
            get_lp_name=self._lp_name, on_change=self._on_recipe_change)
        f.addRow(self._recipe_panel)
        sections.addWidget(rec_sec)

        sections.addStretch(1)

        # --- C4 Actions footer (pinned) --------------------------------------
        footer = QWidget()
        footer.setObjectName("footer")
        flay = QVBoxLayout(footer)
        flay.setContentsMargins(12, 10, 12, 10)

        # Primary "Bake recipe": a two-line label (title + subtitle) and a B kbd hint,
        # laid out inside the button (child labels pass clicks through to the button).
        self._bake_recipe_btn = QPushButton()
        self._bake_recipe_btn.setObjectName("primary")
        self._bake_recipe_btn.clicked.connect(self._bake_recipe)
        bl = QHBoxLayout(self._bake_recipe_btn)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(10)
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        ptitle = QLabel("Bake recipe")
        ptitle.setObjectName("primarytitle")
        self._bake_sub = QLabel("")
        self._bake_sub.setObjectName("primarysub")
        text_col.addWidget(ptitle)
        text_col.addWidget(self._bake_sub)
        bl.addLayout(text_col)
        bl.addStretch(1)
        kbd = QLabel("B")
        kbd.setObjectName("kbd")
        bl.addWidget(kbd)
        for lbl in (ptitle, self._bake_sub, kbd):
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        flay.addWidget(self._bake_recipe_btn)

        # Secondary link row: Export Cage / Export Maps, spacer, Reset cage.
        links = QHBoxLayout()
        links.setContentsMargins(0, 2, 0, 0)
        export_cage = QPushButton("Export Cage")
        export_cage.setObjectName("linkAccent")
        export_cage.clicked.connect(self._save_cage)
        export_maps = QPushButton("Export Maps")
        export_maps.setObjectName("linkSoft")
        export_maps.clicked.connect(self._export)
        reset_cage = QPushButton("Reset cage")
        reset_cage.setObjectName("linkFaint")
        reset_cage.clicked.connect(self._reset_cage)
        links.addWidget(export_cage)
        links.addWidget(export_maps)
        links.addStretch(1)
        links.addWidget(reset_cage)
        links_w = QWidget()
        links_w.setLayout(links)
        flay.addWidget(links_w)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setObjectName("resolved")
        flay.addWidget(self._status)
        outer.addWidget(footer)

        dock.setWidget(container)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._on_recipe_change(self._recipe_panel.recipe())  # seed the button subtitle

    def _build_central(self) -> None:
        """The design's body: a viewport row (3D | 2D side by side) over a separate
        Baked Maps tray. The viewport row is a horizontal splitter so 'Split (3D + 2D)'
        divides left/right; the QtInteractor is inserted at its left in _rebuild and the
        2D UV pane sits at its right. The Baked Maps tray is its own bottom strip,
        independent of the viewport mode."""
        self._viewport_split = QSplitter(Qt.Horizontal)
        self._uv_pane = self._build_uv_pane()
        self._viewport_split.addWidget(self._uv_pane)  # 2D at index 0; 3D inserted left
        # The QtInteractor is inserted at index 0 (left of the 2D pane) in _rebuild.

        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.addWidget(self._viewport_split)
        self._splitter.addWidget(self._build_preview_panel())  # Baked Maps tray
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self.setCentralWidget(self._splitter)

    def _build_uv_pane(self) -> QWidget:
        """The 2D pane (design Region A, '2d'/'split'): a checkerboard UV background
        with the current baked map laid over it and a file/channel caption pill. A
        stand-in for the real UV viewport - it shows the live baked map for now."""
        pane = QWidget()
        pane.setObjectName("uvpane")
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._uv_view = ImageView()  # already paints the checkerboard UV background
        lay.addWidget(self._uv_view, 1)
        cap = QLabel("UV preview")
        cap.setObjectName("uvcaption")
        cap.setAlignment(Qt.AlignCenter)
        lay.addWidget(cap)
        self._uv_caption = cap
        return pane

    def _build_preview_panel(self) -> QWidget:
        """The Baked Maps tray (the design's Region B): a header (title + size + Hide),
        quick tabs (Normal / AO / Curvature), the zoom/pan image view, and a footer
        (full map dropdown, channel isolate, zoom, Export PNG)."""
        panel = QWidget()
        panel.setObjectName("tray")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        header = QHBoxLayout()
        ttl = QLabel("Baked Maps")
        ttl.setObjectName("trayTitle")
        self._tray_size = QLabel("no bake yet")
        self._tray_size.setObjectName("traySize")
        self._tray_hide = QPushButton("Hide")
        self._tray_hide.setObjectName("linkSoft")
        self._tray_hide.clicked.connect(self._toggle_tray)
        header.addWidget(ttl)
        header.addWidget(self._tray_size)
        header.addStretch(1)
        header.addWidget(self._tray_hide)
        lay.addLayout(header)

        # Everything below the header collapses together when the tray is hidden.
        self._tray_body = QWidget()
        body = QVBoxLayout(self._tray_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        lay.addWidget(self._tray_body, 1)

        # Quick tabs for the three core maps (pills); the full list is the footer dropdown.
        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self._tray_tabs = []
        for name in ("Normal", "AO", "Curvature"):
            b = QPushButton(name)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, n=name: self._select_map_by_name(n))
            tabs.addWidget(b)
            self._tray_tabs.append(b)
        tabs.addStretch(1)
        body.addLayout(tabs)

        self._preview = ImageView()
        body.addWidget(self._preview, 1)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self._preview_pick = QComboBox()
        self._preview_pick.currentIndexChanged.connect(self._on_preview_pick)
        self._iso = QComboBox()
        self._iso.addItems(["RGB", "R", "G", "B", "A"])
        self._iso.currentIndexChanged.connect(
            lambda _i: self._show_preview(self._preview_pick.currentIndex()))
        # Before/after difference: pin the current map as a reference, then "Diff" shows
        # the heatmap of the live map against it.
        self._diff_ref: tuple[str, object] | None = None
        pin_btn = QPushButton("Pin ref")
        pin_btn.clicked.connect(self._pin_diff_ref)
        self._diff = QPushButton("Diff")
        self._diff.setCheckable(True)
        self._diff.toggled.connect(
            lambda _c: self._show_preview(self._preview_pick.currentIndex()))
        zoom_out = QPushButton("-")
        zoom_out.clicked.connect(lambda: self._preview.scale(0.8, 0.8))
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(lambda: self._preview.fit())
        zoom_in = QPushButton("+")
        zoom_in.clicked.connect(lambda: self._preview.scale(1.25, 1.25))
        export_btn = QPushButton("Export PNG")
        export_btn.setObjectName("linkAccent")
        export_btn.clicked.connect(self._export_preview)
        footer.addWidget(QLabel("Map"))
        footer.addWidget(self._preview_pick, 1)
        footer.addWidget(QLabel("Isolate"))
        footer.addWidget(self._iso)
        footer.addWidget(pin_btn)
        footer.addWidget(self._diff)
        footer.addWidget(zoom_out)
        footer.addWidget(fit_btn)
        footer.addWidget(zoom_in)
        footer.addWidget(export_btn)
        body.addLayout(footer)

        self._preview_maps: list[tuple[str, object]] = []
        self._preview_panel = panel
        return panel

    def _toggle_tray(self) -> None:
        """Collapse the Baked Maps tray to just its header (design's 'Show baked maps'
        bar) or restore it. Only the tray height changes; the viewport is untouched."""
        collapsed = self._tray_body.isVisible()
        self._tray_body.setVisible(not collapsed)
        self._tray_hide.setText("Show" if collapsed else "Hide")
        total = sum(self._splitter.sizes())
        tray = 34 if collapsed else 178
        self._splitter.setSizes([total - tray, tray])

    def _select_map_by_name(self, name: str) -> None:
        """Tray tab: show the named map if it has been baked."""
        names = [n for n, _img in self._preview_maps]
        for tab in self._tray_tabs:
            tab.setChecked(tab.text() == name)
        if name in names:
            self._preview_pick.setCurrentIndex(names.index(name))

    def _isolated(self, image: np.ndarray) -> np.ndarray:
        """Apply the channel-isolation selection: the full RGB, or one channel shown
        as greyscale. Isolating an absent alpha shows white (no alpha present)."""
        sel = self._iso.currentText()
        arr = np.asarray(image)
        if sel == "RGB":
            return arr
        idx = {"R": 0, "G": 1, "B": 2, "A": 3}[sel]
        if idx < arr.shape[2]:
            gray = arr[..., idx]
        else:
            gray = np.full(arr.shape[:2], 255, np.uint8)
        return np.repeat(gray[..., None], 3, axis=2)

    def _export_preview(self) -> None:
        """Save the currently-viewed map (with the active isolation) to a PNG."""
        idx = self._preview_pick.currentIndex()
        if not (0 <= idx < len(self._preview_maps)):
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PNG", "", "PNG (*.png)")
        if path:
            import imageio.v3 as iio
            iio.imwrite(path, self._isolated(self._preview_maps[idx][1]))
            self._set_status(f"Wrote {path}")

    def _apply_viewport_mode(self) -> None:
        """Show the 2D pane, the 3D pane, or both side by side per the Viewport
        dropdown. The Baked Maps tray is independent (its own Hide/Show)."""
        mode = self._viewport_mode.currentText()
        show_2d = mode in ("2D", "3D + 2D")
        show_3d = mode in ("3D", "3D + 2D")
        self._uv_pane.setVisible(show_2d)
        if self._interactor is not None:
            self._interactor.setVisible(show_3d)
        if show_2d and show_3d:
            self._viewport_split.setSizes([1_000_000, 1_000_000])  # equal left/right
        if hasattr(self, "_status_view"):
            self._refresh_status_meta()

    def _refresh_preview(self) -> None:
        """Repopulate the map dropdown from the editor's in-memory bakes and show the
        current selection (defaulting to the newest map). Called after each bake."""
        self._preview_maps = self.editor.baked_maps()
        keep = self._preview_pick.currentText()
        self._preview_pick.blockSignals(True)
        self._preview_pick.clear()
        self._preview_pick.addItems([name for name, _img in self._preview_maps])
        self._preview_pick.blockSignals(False)
        w, h = self.editor._bake_size
        ss = self.editor._supersample
        self._tray_size.setText(
            f"{w} x {h} · {ss}x SS" if self._preview_maps else "no bake yet")
        if not self._preview_maps:
            self._preview.clear()
            self._refresh_uv_pane()  # still show the UV layout with no bake yet
            return
        names = [name for name, _img in self._preview_maps]
        # Keep the user's current pick if it still exists, else show the last-baked map.
        idx = names.index(keep) if keep in names else len(names) - 1
        self._preview_pick.setCurrentIndex(idx)
        self._show_preview(idx)

    def _on_preview_pick(self, idx: int) -> None:
        self._show_preview(idx)

    def _pin_diff_ref(self) -> None:
        """Pin the currently-shown map as the difference reference (the 'before')."""
        idx = self._preview_pick.currentIndex()
        if 0 <= idx < len(self._preview_maps):
            name, img = self._preview_maps[idx]
            self._diff_ref = (name, np.array(img, copy=True))
            self._set_status(f"Pinned '{name}' as the diff reference.")

    def _show_preview(self, idx: int) -> None:
        if 0 <= idx < len(self._preview_maps):
            name, img = self._preview_maps[idx]
            if self._diff.isChecked() and self._diff_ref is not None:
                try:
                    self._preview.set_image(bake.diff_map(img, self._diff_ref[1]))
                except ValueError:  # size mismatch with the pinned reference
                    self._set_status("Diff needs the same map size as the pinned reference.")
                    self._preview.set_image(self._isolated(img))
            else:
                self._preview.set_image(self._isolated(img))
        self._refresh_uv_pane()

    def _refresh_uv_pane(self) -> None:
        """Draw the low poly's UV island layout in the 2D pane - over the selected baked
        map when one exists (the bake is already in UV space, so this is a UV-space
        texture view with seams), else over a checkerboard. Shows islands, seams and
        wasted UV space even before any bake."""
        uvs = None if self.editor is None else self.editor._cached_low_uvs
        if uvs is None:
            self._uv_view.clear()
            self._uv_caption.setText("UV preview - the low poly has no UVs")
            return
        base = None
        label = "UV layout"
        idx = self._preview_pick.currentIndex()
        if 0 <= idx < len(self._preview_maps):
            name, img = self._preview_maps[idx]
            base = self._isolated(img)
            label = f"UV layout · {name} · {self._iso.currentText()}"
        self._uv_view.set_image(uvlayout.layout_image(uvs, base=base))
        self._uv_caption.setText(label)

    @staticmethod
    def _size_combo() -> QComboBox:
        box = QComboBox()
        for s in _BAKE_SIZES:
            box.addItem(str(s))
        return box

    @staticmethod
    def _labeled(slider: QSlider, label: QLabel) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(slider)
        lay.addWidget(label)
        return row

    def _rebuild(self) -> None:
        """(Re)create the interactor + editor for the current mesh paths and resync the
        dock. Called on startup and whenever File > Open changes a mesh."""
        old = self._interactor
        self._interactor = QtInteractor(self)
        if old is not None:
            old.setParent(None)
            old.close()
        self._viewport_split.insertWidget(0, self._interactor)  # 3D at left of the 2D pane
        self._viewport_split.setStretchFactor(0, 1)
        self._viewport_split.setStretchFactor(1, 1)
        self._splitter.setSizes([678, 178])  # design: ~178px Baked Maps tray

        self.editor = CageEditor(
            self._low_path,
            high_path=self._high_path,
            cage_path=self._cage_path,
            hdr_path=self._hdr_path,
            global_push=self._global_push,
            plotter=self._interactor,
        )
        self.editor.attach_interaction()
        self.editor._on_select = self._sync_selected_offset  # numeric field follows picks
        # Restore a project's saved edits onto the fresh editor before syncing the dock,
        # so the widgets reflect the loaded values. Warn if the source mesh changed.
        if self._pending_editor_state is not None:
            matched = self.editor.apply_authoring_state(self._pending_editor_state)
            self._pending_editor_state = None
            if not matched:
                self._set_status(
                    "Project opened, but the low poly's vertex count changed - cage "
                    "edits and skew were skipped (bake settings kept).")
        self.editor.set_theme(theme.palette_key(self._direction, self._mood))
        self._sync_dock()
        self._refresh_preview()
        self._apply_viewport_mode()
        self._interactor.reset_camera()
        self.setWindowTitle(f"CageBakeCake - {self._low_path}")
        self._asset_label.setText(f"- {os.path.basename(self._low_path)}")
        self._refresh_status_meta()
        self._saved_edits = self._current_edit_sig()  # freshly loaded state is the clean baseline

    def _sync_dock(self) -> None:
        """Push the editor's current ranges/values into the dock widgets without
        triggering their change handlers (which would feed back into the editor)."""
        ed = self.editor
        widgets = (self._offset, self._opacity, self._skew, self._paint_skew,
                   self._paint_value, self._push_brush, self._push_strength,
                   self._smooth_brush, self._smooth_strength, self._vert_offset,
                   self._soft, self._radius,
                   self._low_shaded, self._low_wire, self._high_visible,
                   self._high_shaded, self._high_wire, self._normal_map,
                   self._show_normals, self._miss_overlay,
                   self._cage_points, self._cage_wire,
                   self._bake_w, self._bake_h, self._supersample, self._padding,
                   self._ao_samples, self._explode, self._flip_green,
                   self._name_match, self._mesh_list)
        for w in widgets:
            w.blockSignals(True)
        self._offset.setValue(round(ed.global_push / ed._push_max * _SLIDER_STEPS))
        self._offset_label.setText(f"{ed.global_push:.4f}")
        self._opacity.setValue(35)
        self._skew.setValue(round(ed.skew * _SLIDER_STEPS))
        self._skew_label.setText(f"{ed.skew:.2f}")
        self._paint_skew.setChecked(ed._paint_skew)
        self._paint_value.setValue(round(ed._paint_value * _SLIDER_STEPS))
        self._paint_value_label.setText(f"{ed._paint_value:.2f}")
        self._push_brush.setChecked(ed._push_brush)
        self._push_strength.setValue(round(ed._push_strength * _SLIDER_STEPS))
        self._push_strength_label.setText(f"{ed._push_strength:+.2f}")
        self._smooth_brush.setChecked(ed._smooth_brush)
        self._smooth_strength.setValue(round(ed._smooth_strength * _SLIDER_STEPS))
        self._smooth_strength_label.setText(f"{ed._smooth_strength:.2f}")
        self._vert_offset.setEnabled(ed.selected is not None)
        self._vert_offset.setValue(ed.selected_offset() or 0.0)
        self._symmetry.set_current_index({None: 0, "x": 1, "y": 2, "z": 3}[ed._symmetry])
        self._soft.setChecked(ed.soft_enabled)
        self._radius_max = ed._diag * 0.5
        self._radius.setValue(round(ed.soft_radius / self._radius_max * _SLIDER_STEPS))
        self._radius_label.setText(f"{ed.soft_radius:.3f}")
        self._low_shaded.setChecked(ed._low_style == "shaded")
        self._low_wire.setChecked(ed._low_wire_on)
        has_high = ed.high is not None
        self._high_visible.setChecked(ed._high_visible)
        self._high_visible.setEnabled(has_high)
        self._high_shaded.setChecked(ed._high_style == "shaded")
        self._high_shaded.setEnabled(has_high)
        self._high_wire.setChecked(ed._high_wire_on)
        self._high_wire.setEnabled(has_high)
        self._normal_map.setChecked(ed._normal_map_on)
        self._show_normals.setChecked(ed._normals_glyph_on)
        self._miss_overlay.setChecked(ed._miss_overlay_on)
        self._cage_points.setChecked(True)   # cage_pts starts visible
        self._cage_wire.setChecked(False)
        self._bake_w.setCurrentText(str(ed._bake_size[0]))
        self._bake_h.setCurrentText(str(ed._bake_size[1]))
        self._supersample.setCurrentText(f"{ed._supersample}x")
        self._padding.setCurrentText(str(ed._padding))
        self._ao_samples.setCurrentText(str(ed._ao_samples))
        self._explode.setValue(round(ed._explode / _EXPLODE_MAX * _SLIDER_STEPS))
        self._explode_label.setText(f"{ed._explode:.2f}")
        self._flip_green.setChecked(ed._flip_green)
        self._name_match.setChecked(ed._name_match)
        self._mesh_list.clear()
        for group, idx, label, visible in ed.meshes():
            item = QListWidgetItem(label)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked if visible else Qt.Unchecked)
            item.setData(Qt.UserRole, (group, idx))
            self._mesh_list.addItem(item)
        for w in widgets:
            w.blockSignals(False)
        self._name_table.rebuild()  # repopulate name-match rows for the loaded parts
        self._on_recipe_change(self._recipe_panel.recipe())  # subtitle reflects real bake size

    # --- theming ------------------------------------------------------------
    def _on_direction(self, idx: int) -> None:
        self._direction = theme.DIRECTIONS[idx]
        self._apply_theme()

    def _on_mood(self, idx: int) -> None:
        self._mood = theme.MOODS[idx]
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Re-skin the whole window (QSS) and recolor the viewport for the current
        direction/mood. Pure presentation - no editor state changes."""
        key = theme.palette_key(self._direction, self._mood)
        theme.set_active(key)  # so custom-painted toggles read the live palette
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.build_qss(key))
        if self.editor is not None:
            self.editor.set_theme(key)
        if hasattr(self, "_appmark"):
            self._paint_appmark()  # recolor the cake mark for the new palette
        if hasattr(self, "_status_right"):
            self._refresh_status_meta()
        self.update()  # repaint the custom toggle switches for the new palette

    # --- dock callbacks -----------------------------------------------------
    def _on_offset(self, step: int) -> None:
        value = step / _SLIDER_STEPS * self.editor._push_max
        self.editor._on_push(value)
        self._offset_label.setText(f"{value:.4f}")

    def _on_opacity(self, pct: int) -> None:
        self.editor._on_opacity(pct / 100.0)

    def _on_skew(self, step: int) -> None:
        value = step / _SLIDER_STEPS
        self.editor.set_skew(value)
        self._skew_label.setText(f"{value:.2f}")

    def _on_paint_value(self, step: int) -> None:
        value = step / _SLIDER_STEPS
        self.editor.set_paint_value(value)
        self._paint_value_label.setText(f"{value:.2f}")

    def _on_paint_skew(self, checked: bool) -> None:
        self.editor.set_paint_skew(checked)
        self._sync_brush_toggles()

    def _on_push_brush(self, checked: bool) -> None:
        self.editor.set_push_brush(checked)
        self._sync_brush_toggles()

    def _on_push_strength(self, step: int) -> None:
        value = step / _SLIDER_STEPS
        self.editor.set_push_strength(value)
        self._push_strength_label.setText(f"{value:+.2f}")

    def _on_smooth_brush(self, checked: bool) -> None:
        self.editor.set_smooth_brush(checked)
        self._sync_brush_toggles()

    def _on_smooth_strength(self, step: int) -> None:
        value = step / _SLIDER_STEPS
        self.editor.set_smooth_strength(value)
        self._smooth_strength_label.setText(f"{value:.2f}")

    def _on_symmetry(self, idx: int) -> None:
        self.editor.set_symmetry([None, "x", "y", "z"][idx])

    def _on_vert_offset(self, value: float) -> None:
        self.editor.set_selected_offset(value)

    def _sync_selected_offset(self, idx) -> None:
        """Follow a viewport selection: show the picked vertex's normal offset in the
        numeric field (disabled when nothing is selected). Set by the editor's callback."""
        off = self.editor.selected_offset()
        self._vert_offset.blockSignals(True)
        self._vert_offset.setEnabled(idx is not None)
        self._vert_offset.setValue(off if off is not None else 0.0)
        self._vert_offset.blockSignals(False)

    def _sync_brush_toggles(self) -> None:
        """The left-drag brushes (push / skew / smooth) are mutually exclusive; reflect the
        editor's resolved state back into all three dock toggles without re-emitting."""
        for w, on in ((self._paint_skew, self.editor._paint_skew),
                      (self._push_brush, self.editor._push_brush),
                      (self._smooth_brush, self.editor._smooth_brush)):
            w.blockSignals(True)
            w.setChecked(on)
            w.blockSignals(False)

    def _on_soft(self, checked: bool) -> None:
        self.editor.set_soft_enabled(checked)

    def _on_radius(self, step: int) -> None:
        value = step / _SLIDER_STEPS * self._radius_max
        self.editor.set_soft_radius(value)
        self._radius_label.setText(f"{value:.3f}")

    def _on_bake_size(self, _text: str) -> None:
        self.editor.set_bake_size(int(self._bake_w.currentText()),
                                  int(self._bake_h.currentText()))

    def _on_explode(self, step: int) -> None:
        value = step / _SLIDER_STEPS * _EXPLODE_MAX
        self.editor.set_explode(value)
        self._explode_label.setText(f"{value:.2f}")

    def _on_mesh_toggle(self, item: QListWidgetItem) -> None:
        group, idx = item.data(Qt.UserRole)
        self.editor.set_part_visible(group, idx, item.checkState() == Qt.Checked)

    def _on_name_match(self, checked: bool) -> None:
        self.editor.set_name_match(checked)
        self._name_table.rebuild()  # status flips between manual and derived

    def _on_pair_hover(self, label: str | None) -> None:
        """Name-match row hover: the viewport highlight is driven by the table; this
        mirrors the design's top-center 'Highlighting <part>' pill in the status bar
        (a proper HUD pill arrives with the viewport overlays)."""
        if label:
            self.statusBar().showMessage(f"Highlighting {label}")
        else:
            self.statusBar().showMessage(self._status.text())

    # --- menu / button actions ----------------------------------------------
    def _reset_cage(self) -> None:
        self.editor._reset_cage()

    def _reset_point(self) -> None:
        self.editor._reset_selected()

    def _progress(self, msg: str) -> None:
        """Bake progress callback: show it and pump the event loop so the Cancel button
        (and per-sample AO progress) stay responsive during a bake."""
        self._set_status(msg)
        QApplication.processEvents()

    def _cancel_bake(self) -> None:
        self._cancel = True

    # --- threaded bake harness ----------------------------------------------
    def _run_bake(self, compute, on_done, busy_msg: str) -> bool:
        """Run `compute(emit)` (a pure ray-cast closure) on a worker thread, keeping the
        UI live; call `on_done(result)` on the main thread when it finishes. `compute`
        must not touch Qt/VTK. Returns False (and does nothing) if a bake is already
        running - bakes do not overlap."""
        if self._bake_busy:
            self._set_status("A bake is already running.")
            return False
        self._bake_busy = True
        self._cancel = False
        self._set_status(busy_msg)

        thread = QThread()
        worker = _BakeWorker(compute)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._set_status)  # queued to the main thread

        def finish(result):
            thread.quit()
            thread.wait()
            worker.deleteLater()
            self._bake_busy = False
            self._bake_thread = None
            self._bake_worker = None
            if not self._closing:
                on_done(result)

        worker.finished.connect(finish)
        self._bake_thread = thread
        self._bake_worker = worker
        thread.start()
        return True

    def _mark_shaded_normal(self) -> None:
        """Reflect the post-bake low-poly state (shaded + normal map) in the dock."""
        for w, checked in ((self._low_shaded, True), (self._normal_map, True)):
            w.blockSignals(True)
            w.setChecked(checked)
            w.blockSignals(False)

    def _bake(self) -> None:
        job = self.editor.bake_inputs()
        if job is None:
            self._set_status("Bake needs a high poly with UVs.")
            return

        def compute(emit):
            return bake.bake(**job["kwargs"], progress=emit,
                             should_cancel=lambda: self._cancel)

        def done(result):
            if isinstance(result, Exception):
                self._set_status(f"Bake failed: {result}")
                return
            baked = self.editor.apply_bake_result(result, job)
            self._mark_shaded_normal()
            self._set_status(
                "Baked. Toggle 'Normal map' / 'Low poly shaded' to compare." if baked
                else "Bake cancelled.")
            self._refresh_preview()

        self._run_bake(compute, done, "Baking (this can take a while)...")

    def closeEvent(self, event):
        """Warn on unsaved cage edits, then stop a running bake cleanly before closing so
        the worker thread is not destroyed mid-run."""
        if (self.editor is not None and self._saved_edits is not None
                and self._current_edit_sig() != self._saved_edits):
            resp = QMessageBox.question(
                self, "Unsaved cage edits",
                "You have unsaved cage edits. Save them to a project before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if resp == QMessageBox.Cancel:
                event.ignore()
                return
            if resp == QMessageBox.Save:
                self._save_project()
        self._closing = True
        if self._bake_busy and self._bake_thread is not None:
            self._cancel = True
            self._bake_thread.quit()
            self._bake_thread.wait()
        super().closeEvent(event)

    def _lp_name(self) -> str:
        """The low-poly stem, for {LP} expansion in packing filenames."""
        return os.path.splitext(os.path.basename(self._low_path))[0]

    def _on_recipe_change(self, rec) -> None:
        """Reflect the recipe's map/output counts on the primary button subtitle (the
        design's '<n> maps -> <n> textures' line)."""
        w = self._bake_w.currentText() if hasattr(self, "_bake_w") else "2048"
        self._bake_sub.setText(
            f"{len(rec.bake_maps)} maps -> {len(rec.outputs)} textures · {w}px")

    def _bake_recipe(self) -> None:
        """Bake the current recipe: every map it needs, packed into its output PNGs
        next to the low poly. The primary dock action."""
        if self._bake_busy:
            self._set_status("A bake is already running.")
            return
        self._cancel = False
        self._set_status("Baking recipe (this can take a while)...")
        QApplication.processEvents()
        written = self.editor.bake_recipe(
            self._recipe_panel.recipe(), progress=self._progress,
            should_cancel=lambda: self._cancel)
        if written is None:
            self._set_status("Recipe bake cancelled.")
        else:
            names = ", ".join(os.path.basename(p) for p in written)
            self._set_status(f"Recipe baked: {len(written)} texture(s) -> {names}")
        # The normal bake switches the low poly to shaded + normal map; reflect that.
        for w, checked in ((self._low_shaded, True), (self._normal_map, True)):
            w.blockSignals(True)
            w.setChecked(checked)
            w.blockSignals(False)
        self._refresh_preview()

    def _bake_ao(self) -> None:
        job = self.editor.ao_inputs()
        if job is None:
            self._set_status("AO needs a high poly with UVs.")
            return

        def compute(emit):
            return bake.bake_ao(**job["kwargs"], progress=emit,
                                should_cancel=lambda: self._cancel)

        def done(result):
            if isinstance(result, Exception):
                self._set_status(f"AO failed: {result}")
                return
            ok = self.editor.apply_ao_result(result, job)
            self._set_status("AO baked (next to the low poly)." if ok else "AO cancelled.")
            self._refresh_preview()

        self._run_bake(compute, done, "Baking AO (this can take a while)...")

    def _bake_curvature(self) -> None:
        if self._bake_busy:
            self._set_status("A bake is already running.")
            return
        self.editor._bake_curvature()
        self._set_status("Curvature baked (from the last normal-map bake).")
        self._refresh_preview()

    def _bake_height(self) -> None:
        if self._bake_busy:
            self._set_status("A bake is already running.")
            return
        self._set_status("Baking height...")
        QApplication.processEvents()
        self.editor._bake_height(progress=self._progress)
        self._set_status("Height baked (next to the low poly).")
        self._refresh_preview()

    def _bake_position(self) -> None:
        if self._bake_busy:
            self._set_status("A bake is already running.")
            return
        self._set_status("Baking position...")
        QApplication.processEvents()
        self.editor._bake_position(progress=self._progress)
        self._set_status("Position baked (next to the low poly).")
        self._refresh_preview()

    def _rebake(self) -> None:
        """Incremental re-bake of just the changed cage region (falls back to a full
        bake when that is not possible - see CageEditor.rebake)."""
        if self._bake_busy:
            self._set_status("A bake is already running.")
            return
        self._set_status("Re-baking changed region...")
        QApplication.processEvents()
        self.editor.rebake(progress=self._progress)
        self._mark_shaded_normal()
        self._refresh_preview()

    def _open_low(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Low Poly", "", _USD_FILTER)
        if path:
            self._low_path = path
            self._cage_path = None  # the cage tracks the low poly's topology
            self._rebuild()
            self._remember_recent(path)

    # --- recent files + drag-and-drop --------------------------------------
    def _recent(self) -> list:
        return [p for p in (self._settings.value("recent", []) or []) if p]

    def _remember_recent(self, path: str) -> None:
        self._settings.setValue("recent", project.mru_add(self._recent(), path))
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = self._recent()
        if not recent:
            act = self._recent_menu.addAction("(none)")
            act.setEnabled(False)
            return
        for p in recent:
            self._recent_menu.addAction(p, lambda _c=False, path=p: self._open_path(path))

    @staticmethod
    def _is_openable(path: str) -> bool:
        return path.lower().endswith((".usd", ".usdc", ".usda", ".cbcproj"))

    def _open_path(self, path: str) -> None:
        """Open a mesh or project by path (recent menu / drag-and-drop)."""
        if path.lower().endswith(".cbcproj"):
            self._open_project_path(path)
        else:
            self._low_path = path
            self._cage_path = None
            self._rebuild()
            self._remember_recent(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
                self._is_openable(u.toLocalFile()) for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for u in event.mimeData().urls():
            p = u.toLocalFile()
            if self._is_openable(p):
                self._open_path(p)
                break

    def _open_high(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open High Poly", "", _USD_FILTER)
        if path:
            self._high_path = path
            self._rebuild()

    def _save_cage(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Cage As", "", _USD_FILTER)
        if not path:
            return
        out = self.editor.save_cage(path)
        self._set_status(f"Saved cage -> {out}")

    # --- project / session --------------------------------------------------
    def _save_project(self) -> None:
        """Write the whole session (mesh paths + cage edits + skew + bake settings +
        recipe + theme) to a .cbcproj so a cage edit survives a restart."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", "", _PROJECT_FILTER)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".cbcproj"
        base = os.path.dirname(os.path.abspath(path))
        doc = project.build_document(
            paths={
                "low": project.relativize(self._low_path, base),
                "high": project.relativize(self._high_path, base),
                "cage": project.relativize(self._cage_path, base),
                "hdr": project.relativize(self._hdr_path, base),
            },
            theme={"direction": self._direction, "mood": self._mood},
            recipe=self._recipe_panel.recipe(),
            edits=self.editor.authoring_state(),
        )
        project.save(path, doc)
        self._project_path = path
        self._saved_edits = self._current_edit_sig()  # this state is now the clean baseline
        self._remember_recent(path)
        self._set_status(f"Saved project -> {os.path.basename(path)}")

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", _PROJECT_FILTER)
        if path:
            self._open_project_path(path)

    def _open_project_path(self, path: str) -> None:
        """Load a .cbcproj: restore the mesh paths, theme and recipe, then rebuild the
        editor and apply the saved cage edits / skew / bake settings."""
        try:
            data = project.load(path)
        except (OSError, ValueError) as exc:  # bad JSON / not a project
            self._set_status(f"Could not open project: {exc}")
            return
        base = os.path.dirname(os.path.abspath(path))
        paths = data.get("paths") or {}
        low = project.resolve(paths.get("low"), base)
        if not low or not os.path.exists(low):
            self._set_status(f"Project's low poly is missing: {low}")
            return
        self._low_path = low
        self._high_path = project.resolve(paths.get("high"), base)
        self._cage_path = project.resolve(paths.get("cage"), base)
        self._hdr_path = project.resolve(paths.get("hdr"), base)
        self._global_push = None  # the saved edits carry the push
        self._set_theme_axes((data.get("theme") or {}))
        if data.get("recipe"):
            self._recipe_panel.set_recipe(recipe.Recipe.from_dict(data["recipe"]))
        self._pending_editor_state = data.get("edits")
        self._project_path = path
        self._rebuild()       # builds the editor and applies the staged edits
        self._apply_theme()   # re-skin for the restored direction/mood
        self._remember_recent(path)
        self._set_status(f"Opened project {os.path.basename(path)}")

    def _current_edit_sig(self):
        """A signature of the cage edits (push + manual delta + skew) for the unsaved-edits
        quit guard; bake settings / theme are excluded so tweaking them does not nag."""
        ed = self.editor
        if ed is None:
            return None
        return project.encode_edits(ed.global_push, ed.manual_delta, ed.skew, ed.skew_map)

    def _set_theme_axes(self, th: dict) -> None:
        """Set the direction/mood from a loaded project, reflecting them in the title-bar
        segmented controls (set_current_index does not re-emit, so no feedback loop)."""
        direction = th.get("direction")
        mood = th.get("mood")
        if direction in theme.DIRECTIONS:
            self._direction = direction
            self._direction_pick.set_current_index(theme.DIRECTIONS.index(direction))
        if mood in theme.MOODS:
            self._mood = mood
            self._mood_pick.set_current_index(theme.MOODS.index(mood))

    def _export(self) -> None:
        if self._bake_busy:
            self._set_status("A bake is already running.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Normal Map", "", "PNG (*.png)")
        if not path:
            return
        self._set_status(f"Baking to {path}...")
        QApplication.processEvents()
        self.editor._bake(out_path=path)
        self._set_status(f"Wrote {path}")

    def _build_statusbar(self) -> None:
        """The design's status bar: a recipe-status dot + text, the cage vert count, and
        the current view on the left; the active theme mood label on the right."""
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.setFixedHeight(30)
        self._status_dot = QLabel()
        self._status_dot.setObjectName("statusdot")
        self._status_main = QLabel("Ready")
        self._status_main.setObjectName("statusseg")
        self._status_verts = QLabel("")
        self._status_verts.setObjectName("statusseg")
        self._status_view = QLabel("")
        self._status_view.setObjectName("statusseg")
        for w in (self._status_dot, self._status_main, _sep(), self._status_verts,
                  _sep(), self._status_view):
            sb.addWidget(w)
        self._status_right = QLabel("")
        self._status_right.setObjectName("statusright")
        sb.addPermanentWidget(self._status_right)

    def _refresh_status_meta(self) -> None:
        """Update the non-message status segments (vert count, view, theme label)."""
        if self.editor is not None:
            verts = len(self.editor.cage.points)
            self._status_verts.setText(f"{verts:,} cage verts")
        self._status_view.setText(f"{self._viewport_mode.currentText()} view")
        direction = "Patisserie" if self._direction == "A" else "Chocolatier"
        self._status_right.setText(f"{direction} · {self._mood.capitalize()}")

    def _set_status(self, msg: str) -> None:
        self._status.setText(msg)
        if hasattr(self, "_status_main"):
            self._status_main.setText(msg)
        self.statusBar().showMessage(msg)


def _sep() -> QLabel:
    lbl = QLabel("·")
    lbl.setObjectName("statusseg")
    return lbl


def _helper(text: str) -> QLabel:
    """A wrapped helper paragraph under a section title, as in the design."""
    lbl = QLabel(text)
    lbl.setObjectName("helper")
    lbl.setWordWrap(True)
    return lbl


def _slider_field(caption: str, slider: QSlider, value: QLabel) -> QWidget:
    """A slider row in the design's shape: caption on the left and the live value on
    the right, over a full-width track below."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 2, 0, 2)
    v.setSpacing(3)
    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    cap = QLabel(caption)
    cap.setObjectName("fieldcap")
    value.setObjectName("fieldval")
    top.addWidget(cap)
    top.addStretch(1)
    top.addWidget(value)
    v.addLayout(top)
    v.addWidget(slider)
    return w


def _toggle_row(text: str, toggle: QWidget) -> QWidget:
    """A toggle row: a label on the left, the pill switch pinned to the right."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 2, 0, 2)
    cap = QLabel(text)
    cap.setObjectName("fieldcap")
    h.addWidget(cap)
    h.addStretch(1)
    h.addWidget(toggle)
    return w


def launch(
    low_path: str,
    high_path: str | None = None,
    cage_path: str | None = None,
    hdr_path: str | None = None,
    global_push: float | None = None,
) -> None:
    """Open the Qt application window and run the event loop until the user quits."""
    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    win = MainWindow(low_path, high_path, cage_path, hdr_path, global_push)
    win.show()
    app.exec()
