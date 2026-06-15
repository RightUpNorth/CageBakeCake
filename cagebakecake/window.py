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

import numpy as np
from pyvistaqt import QtInteractor
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
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
_SLIDER_STEPS = 1000  # integer resolution for the float-valued sliders
_BAKE_SIZES = [256, 512, 1024, 2048, 4096, 8192, 16384]  # normal-map width/height choices


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
        self.resize(1280, 800)

        self._low_path = low_path
        self._high_path = high_path
        self._cage_path = cage_path
        self._hdr_path = hdr_path
        self._global_push = global_push

        self._interactor: QtInteractor | None = None
        self.editor: CageEditor | None = None
        self._cancel = False  # set by the Cancel button, polled by the AO bake loop

        # Theme axes (direction + mood) drive the 6-palette matrix; see theme.py.
        self._direction = theme.DEFAULT_DIRECTION
        self._mood = theme.DEFAULT_MOOD

        self._build_menu()
        self._build_toolbar()
        self._build_dock()
        self._build_central()
        self._build_statusbar()
        self._rebuild()
        self._apply_theme()

    # --- construction -------------------------------------------------------
    def _build_toolbar(self) -> None:
        """The design's title bar, recreated as a themed top toolbar (the OS title bar is
        native): app mark + title + asset name on the left; the Direction/Mood segmented
        toggles, the viewport-mode dropdown, and three window dots on the right."""
        bar = self.addToolBar("Title")
        bar.setObjectName("titlebar")
        bar.setMovable(False)

        mark = QLabel()
        mark.setObjectName("appmark")
        mark.setFixedSize(22, 22)
        title = QLabel("CageBakeCake")
        title.setObjectName("apptitle")
        self._asset_label = QLabel("")
        self._asset_label.setObjectName("assetname")
        bar.addWidget(mark)
        bar.addWidget(title)
        bar.addWidget(self._asset_label)

        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)

        self._viewport_mode = QComboBox()
        self._viewport_mode.addItems(["3D", "3D + 2D", "2D"])
        self._viewport_mode.setCurrentText("3D + 2D")
        self._viewport_mode.currentTextChanged.connect(lambda _t: self._apply_viewport_mode())
        bar.addWidget(self._viewport_mode)

        theme_label = QLabel("THEME")
        theme_label.setObjectName("themelabel")
        bar.addWidget(theme_label)
        self._direction_pick = SegmentedControl(["Patisserie", "Chocolatier"])  # A, B
        self._direction_pick.changed.connect(self._on_direction)
        bar.addWidget(self._direction_pick)
        self._mood_pick = SegmentedControl(["Light", "Neutral", "Dark"])
        self._mood_pick.changed.connect(self._on_mood)
        bar.addWidget(self._mood_pick)

        dots = QWidget()
        dlay = QHBoxLayout(dots)
        dlay.setContentsMargins(8, 0, 0, 0)
        dlay.setSpacing(5)
        for i in range(3):
            d = QLabel()
            d.setProperty("dot", "on" if i == 2 else "off")
            dlay.addWidget(d)
        bar.addWidget(dots)

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        file_menu.addAction("Open Low Poly...", self._open_low)
        file_menu.addAction("Open High Poly...", self._open_high)
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
        bake_menu.addAction("Bake AO", self._bake_ao)
        bake_menu.addAction("Bake curvature", self._bake_curvature)
        bake_menu.addAction("Cancel bake", self._cancel_bake)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction("Keyboard shortcuts", lambda: self._set_status(
            "B bake recipe  ·  O soft-select  ·  Z undo  ·  see docs/ for the full list"))

        # The faint caption the design floats at the right of the menu bar.
        caption = QLabel("USD · PySide6 · headless math  ")
        caption.setObjectName("caption")
        bar.setCornerWidget(caption, Qt.TopRightCorner)

    def _build_dock(self) -> None:
        """The controls dock, grouped into the design's sections (Shape the Cage /
        Name match / Recipe) inside a scroll area, with a pinned Actions footer. The
        widgets and their editor callbacks are unchanged from the old flat form - only
        their grouping and the primary 'Bake recipe' action are new."""
        dock = QDockWidget("Controls", self)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

        container = QWidget()
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
        self._offset = QSlider(Qt.Horizontal)
        self._offset.setRange(0, _SLIDER_STEPS)
        self._offset.valueChanged.connect(self._on_offset)
        self._offset_label = QLabel("-")
        f.addRow("Cage offset", self._labeled(self._offset, self._offset_label))

        self._skew = QSlider(Qt.Horizontal)
        self._skew.setRange(0, _SLIDER_STEPS)
        self._skew.valueChanged.connect(self._on_skew)
        self._skew_label = QLabel("-")
        f.addRow("Skew (hard..soft)", self._labeled(self._skew, self._skew_label))

        self._soft = ToggleSwitch("Soft select (proportional)")
        self._soft.toggled.connect(self._on_soft)
        f.addRow(self._soft)

        self._radius = QSlider(Qt.Horizontal)
        self._radius.setRange(1, _SLIDER_STEPS)
        self._radius.valueChanged.connect(self._on_radius)
        self._radius_label = QLabel("-")
        f.addRow("Soft radius", self._labeled(self._radius, self._radius_label))

        self._paint_skew = ToggleSwitch("Paint skew (left-drag, brush = soft radius)")
        self._paint_skew.toggled.connect(lambda v: self.editor.set_paint_skew(v))
        f.addRow(self._paint_skew)

        self._paint_value = QSlider(Qt.Horizontal)
        self._paint_value.setRange(0, _SLIDER_STEPS)
        self._paint_value.valueChanged.connect(self._on_paint_value)
        self._paint_value_label = QLabel("-")
        f.addRow("Brush skew", self._labeled(self._paint_value, self._paint_value_label))
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
        self._name_match = ToggleSwitch("Link low/high parts by prim name")
        self._name_match.toggled.connect(self._on_name_match)
        f.addRow(self._name_match)
        self._name_table = NameMatchTable(lambda: self.editor, on_hover=self._on_pair_hover)
        f.addRow(self._name_table)
        sections.addWidget(nm_sec)

        # --- C3 Recipe --------------------------------------------------------
        rec_sec = CollapsibleSection("Recipe")
        f = rec_sec.form()
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
        # Individual (per-type) bakes, kept available alongside the packed recipe bake.
        indiv = QGridLayout()
        for col, (text, slot) in enumerate((
            ("Bake normal", self._bake), ("Bake AO", self._bake_ao),
            ("Bake curvature", self._bake_curvature))):
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
        """The central area is a vertical splitter matching the design: the 3D viewport
        fills the top, the 2D Baked Maps tray sits below it. The viewport (QtInteractor)
        is inserted at the top in _rebuild; the Viewport dropdown toggles each pane."""
        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.addWidget(self._build_preview_panel())  # the bottom tray for now
        # The QtInteractor is inserted at index 0 (top) in _rebuild.
        self.setCentralWidget(self._splitter)

    def _build_preview_panel(self) -> QWidget:
        """The 2D bake-map viewer panel: a Map dropdown + Fit over a zoom/pan image view.
        The dropdown only lists maps that have actually been baked."""
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(2, 2, 2, 2)

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        self._preview_pick = QComboBox()
        self._preview_pick.currentIndexChanged.connect(self._on_preview_pick)
        # Channel isolation: view the full map or one channel as greyscale. Packed
        # recipe outputs are RGBA, so each channel is independently inspectable.
        self._iso = QComboBox()
        self._iso.addItems(["RGB", "R", "G", "B", "A"])
        self._iso.currentIndexChanged.connect(
            lambda _i: self._show_preview(self._preview_pick.currentIndex()))
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(lambda: self._preview.fit())
        export_btn = QPushButton("Export PNG")
        export_btn.clicked.connect(self._export_preview)
        row_lay.addWidget(QLabel("Map"))
        row_lay.addWidget(self._preview_pick, 1)
        row_lay.addWidget(QLabel("Isolate"))
        row_lay.addWidget(self._iso)
        row_lay.addWidget(fit_btn)
        row_lay.addWidget(export_btn)
        lay.addWidget(row)

        self._preview = ImageView()
        lay.addWidget(self._preview, 1)
        self._preview_maps: list[tuple[str, object]] = []
        self._preview_panel = panel
        return panel

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
        """Show the 2D pane, the 3D pane, or both per the Viewport dropdown; an equal
        split when both are visible."""
        mode = self._viewport_mode.currentText()
        show_2d = mode in ("2D", "3D + 2D")
        show_3d = mode in ("3D", "3D + 2D")
        self._preview_panel.setVisible(show_2d)
        if self._interactor is not None:
            self._interactor.setVisible(show_3d)
        if show_2d and show_3d:
            # Viewport dominant on top, the Baked Maps tray a shorter strip below it
            # (~3:1), matching the design's layout.
            self._splitter.setSizes([3_000_000, 1_000_000])
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
        if not self._preview_maps:
            self._preview.clear()
            return
        names = [name for name, _img in self._preview_maps]
        # Keep the user's current pick if it still exists, else show the last-baked map.
        idx = names.index(keep) if keep in names else len(names) - 1
        self._preview_pick.setCurrentIndex(idx)
        self._show_preview(idx)

    def _on_preview_pick(self, idx: int) -> None:
        self._show_preview(idx)

    def _show_preview(self, idx: int) -> None:
        if 0 <= idx < len(self._preview_maps):
            self._preview.set_image(self._isolated(self._preview_maps[idx][1]))

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
        self._splitter.insertWidget(0, self._interactor)  # top pane = 3D viewport

        self.editor = CageEditor(
            self._low_path,
            high_path=self._high_path,
            cage_path=self._cage_path,
            hdr_path=self._hdr_path,
            global_push=self._global_push,
            plotter=self._interactor,
        )
        self.editor.attach_interaction()
        self.editor.set_theme(theme.palette_key(self._direction, self._mood))
        self._sync_dock()
        self._refresh_preview()
        self._apply_viewport_mode()
        self._interactor.reset_camera()
        self.setWindowTitle(f"CageBakeCake - {self._low_path}")
        self._asset_label.setText(f"- {os.path.basename(self._low_path)}")
        self._refresh_status_meta()

    def _sync_dock(self) -> None:
        """Push the editor's current ranges/values into the dock widgets without
        triggering their change handlers (which would feed back into the editor)."""
        ed = self.editor
        widgets = (self._offset, self._opacity, self._skew, self._paint_skew,
                   self._paint_value, self._soft, self._radius,
                   self._low_shaded, self._low_wire, self._high_visible,
                   self._high_shaded, self._high_wire, self._normal_map,
                   self._show_normals, self._cage_points, self._cage_wire,
                   self._bake_w, self._bake_h, self._supersample, self._padding,
                   self._ao_samples, self._name_match, self._mesh_list)
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
        self._cage_points.setChecked(True)   # cage_pts starts visible
        self._cage_wire.setChecked(False)
        self._bake_w.setCurrentText(str(ed._bake_size[0]))
        self._bake_h.setCurrentText(str(ed._bake_size[1]))
        self._supersample.setCurrentText(f"{ed._supersample}x")
        self._padding.setCurrentText(str(ed._padding))
        self._ao_samples.setCurrentText(str(ed._ao_samples))
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

    def _on_soft(self, checked: bool) -> None:
        self.editor.set_soft_enabled(checked)

    def _on_radius(self, step: int) -> None:
        value = step / _SLIDER_STEPS * self._radius_max
        self.editor.set_soft_radius(value)
        self._radius_label.setText(f"{value:.3f}")

    def _on_bake_size(self, _text: str) -> None:
        self.editor.set_bake_size(int(self._bake_w.currentText()),
                                  int(self._bake_h.currentText()))

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

    def _bake(self) -> None:
        self._cancel = False
        self._set_status("Baking (this can take a while)...")
        QApplication.processEvents()
        self.editor._bake(progress=self._progress, should_cancel=lambda: self._cancel)
        # The bake switches the low poly to shaded + normal map; reflect that in the dock.
        for w, checked in ((self._low_shaded, True), (self._normal_map, True)):
            w.blockSignals(True)
            w.setChecked(checked)
            w.blockSignals(False)
        self._set_status("Bake cancelled." if self._cancel
                         else "Baked. Toggle 'Normal map' / 'Low poly shaded' to compare.")
        self._refresh_preview()

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
        self._cancel = False
        self._set_status("Baking AO (this can take a while)...")
        QApplication.processEvents()
        self.editor._bake_ao(progress=self._progress, should_cancel=lambda: self._cancel)
        self._set_status("AO cancelled." if self._cancel else "AO baked (next to the low poly).")
        self._refresh_preview()

    def _bake_curvature(self) -> None:
        self.editor._bake_curvature()
        self._set_status("Curvature baked (from the last normal-map bake).")
        self._refresh_preview()

    def _open_low(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Low Poly", "", _USD_FILTER)
        if path:
            self._low_path = path
            self._cage_path = None  # the cage tracks the low poly's topology
            self._rebuild()

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

    def _export(self) -> None:
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
