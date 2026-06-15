"""Qt front end: a real application window around the CageEditor viewport.

The interaction logic (pick a cage vertex, drag the gizmo, shift-drag the lighting,
bake) all lives in app.CageEditor and is format/UI-blind. This module is a thin Qt
shell: it embeds a pyvistaqt.QtInteractor as the render surface, drives the editor's
sliders/toggles from dock widgets and a menu bar, and rebuilds the editor when the
user opens different meshes. The standalone pyvista.Plotter path (app.run) is still
the headless / screenshot route and is unaffected.
"""

from __future__ import annotations

from pyvistaqt import QtInteractor
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .app import CageEditor
from .imageview import ImageView

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

        self._build_menu()
        self._build_dock()
        self._build_preview_dock()
        self._rebuild()

    # --- construction -------------------------------------------------------
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

    def _build_dock(self) -> None:
        dock = QDockWidget("Controls", self)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        panel = QWidget()
        form = QFormLayout(panel)

        self._offset = QSlider(Qt.Horizontal)
        self._offset.setRange(0, _SLIDER_STEPS)
        self._offset.valueChanged.connect(self._on_offset)
        self._offset_label = QLabel("-")
        form.addRow("Cage offset", self._labeled(self._offset, self._offset_label))

        self._opacity = QSlider(Qt.Horizontal)
        self._opacity.setRange(0, 100)
        self._opacity.valueChanged.connect(self._on_opacity)
        form.addRow("Cage opacity", self._opacity)

        self._skew = QSlider(Qt.Horizontal)
        self._skew.setRange(0, _SLIDER_STEPS)
        self._skew.valueChanged.connect(self._on_skew)
        self._skew_label = QLabel("-")
        form.addRow("Skew (hard..soft)", self._labeled(self._skew, self._skew_label))

        self._paint_skew = QCheckBox("Paint skew (left-drag, brush = soft radius)")
        self._paint_skew.toggled.connect(lambda v: self.editor.set_paint_skew(v))
        form.addRow(self._paint_skew)

        self._paint_value = QSlider(Qt.Horizontal)
        self._paint_value.setRange(0, _SLIDER_STEPS)
        self._paint_value.valueChanged.connect(self._on_paint_value)
        self._paint_value_label = QLabel("-")
        form.addRow("Brush skew", self._labeled(self._paint_value, self._paint_value_label))

        self._soft = QCheckBox("Soft select")
        self._soft.toggled.connect(self._on_soft)
        form.addRow(self._soft)

        self._radius = QSlider(Qt.Horizontal)
        self._radius.setRange(1, _SLIDER_STEPS)
        self._radius.valueChanged.connect(self._on_radius)
        self._radius_label = QLabel("-")
        form.addRow("Soft radius", self._labeled(self._radius, self._radius_label))

        # Display toggles. Low and high carry independent material switches; the cage and
        # its normals stay visible in every mode.
        self._low_shaded = QCheckBox("Low poly shaded")
        self._low_shaded.toggled.connect(lambda v: self.editor.set_low_style(v))
        form.addRow(self._low_shaded)

        self._low_wire = QCheckBox("Low poly wireframe")
        self._low_wire.toggled.connect(lambda v: self.editor.set_low_wire(v))
        form.addRow(self._low_wire)

        self._high_visible = QCheckBox("High poly visible")
        self._high_visible.toggled.connect(lambda v: self.editor.set_high_visible(v))
        form.addRow(self._high_visible)

        self._high_shaded = QCheckBox("High poly shaded")
        self._high_shaded.toggled.connect(lambda v: self.editor.set_high_style(v))
        form.addRow(self._high_shaded)

        self._high_wire = QCheckBox("High poly wireframe")
        self._high_wire.toggled.connect(lambda v: self.editor.set_high_wire(v))
        form.addRow(self._high_wire)

        self._normal_map = QCheckBox("Normal map (shaded low)")
        self._normal_map.toggled.connect(lambda v: self.editor.set_normal_map(v))
        form.addRow(self._normal_map)

        self._show_normals = QCheckBox("Show LP normals")
        self._show_normals.toggled.connect(lambda v: self.editor.set_low_normals(v))
        form.addRow(self._show_normals)

        self._cage_points = QCheckBox("Cage points")
        self._cage_points.toggled.connect(lambda v: self.editor.set_cage_points(v))
        form.addRow(self._cage_points)

        self._cage_wire = QCheckBox("Cage wireframe")
        self._cage_wire.toggled.connect(lambda v: self.editor.set_cage_wire(v))
        form.addRow(self._cage_wire)

        # Per-mesh visibility checklist (one row per prim in the loaded files).
        self._name_match = QCheckBox("Name match (link low/high by prim name)")
        self._name_match.toggled.connect(lambda v: self.editor.set_name_match(v))
        form.addRow(self._name_match)

        self._mesh_list = QListWidget()
        self._mesh_list.setMaximumHeight(120)
        self._mesh_list.itemChanged.connect(self._on_mesh_toggle)
        form.addRow("Meshes", self._mesh_list)

        # Bake size: independent width and height (a non-square map is allowed).
        self._bake_w = self._size_combo()
        self._bake_h = self._size_combo()
        self._bake_w.currentTextChanged.connect(self._on_bake_size)
        self._bake_h.currentTextChanged.connect(self._on_bake_size)
        form.addRow("Bake width", self._bake_w)
        form.addRow("Bake height", self._bake_h)

        self._supersample = QComboBox()
        for s in (1, 2, 4):
            self._supersample.addItem(f"{s}x")
        self._supersample.currentTextChanged.connect(
            lambda t: self.editor.set_supersample(int(t.rstrip("x"))))
        form.addRow("Supersample", self._supersample)

        self._padding = QComboBox()
        for p in (0, 2, 4, 8, 16, 32):
            self._padding.addItem(str(p))
        self._padding.currentTextChanged.connect(lambda t: self.editor.set_padding(int(t)))
        form.addRow("Edge padding", self._padding)

        self._ao_samples = QComboBox()
        for s in (16, 32, 64, 128, 256):
            self._ao_samples.addItem(str(s))
        self._ao_samples.currentTextChanged.connect(lambda t: self.editor.set_ao_samples(int(t)))
        form.addRow("AO samples", self._ao_samples)

        bake_btn = QPushButton("Bake")
        bake_btn.clicked.connect(self._bake)
        form.addRow(bake_btn)

        ao_btn = QPushButton("Bake AO")
        ao_btn.clicked.connect(self._bake_ao)
        form.addRow(ao_btn)

        curv_btn = QPushButton("Bake Curvature")
        curv_btn.clicked.connect(self._bake_curvature)
        form.addRow(curv_btn)

        cancel_btn = QPushButton("Cancel bake")
        cancel_btn.clicked.connect(self._cancel_bake)
        form.addRow(cancel_btn)

        reset_cage_btn = QPushButton("Reset Cage")
        reset_cage_btn.clicked.connect(self._reset_cage)
        form.addRow(reset_cage_btn)

        reset_pt_btn = QPushButton("Reset Selected Point")
        reset_pt_btn.clicked.connect(self._reset_point)
        form.addRow(reset_pt_btn)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        form.addRow(self._status)

        dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_preview_dock(self) -> None:
        """A 2D viewer for the baked maps (normal / AO / curvature). Sits in the bottom
        dock area; the map dropdown only lists maps that have actually been baked."""
        dock = QDockWidget("Bake preview", self)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(2, 2, 2, 2)

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        self._preview_pick = QComboBox()
        self._preview_pick.currentIndexChanged.connect(self._on_preview_pick)
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(lambda: self._preview.fit())
        row_lay.addWidget(QLabel("Map"))
        row_lay.addWidget(self._preview_pick, 1)
        row_lay.addWidget(fit_btn)
        lay.addWidget(row)

        self._preview = ImageView()
        lay.addWidget(self._preview, 1)
        self._preview_maps: list[tuple[str, object]] = []

        dock.setWidget(panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

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
            self._preview.set_image(self._preview_maps[idx][1])

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
        self.setCentralWidget(self._interactor)
        if old is not None:
            old.close()

        self.editor = CageEditor(
            self._low_path,
            high_path=self._high_path,
            cage_path=self._cage_path,
            hdr_path=self._hdr_path,
            global_push=self._global_push,
            plotter=self._interactor,
        )
        self.editor.attach_interaction()
        self._sync_dock()
        self._refresh_preview()
        self._interactor.reset_camera()
        self.setWindowTitle(f"CageBakeCake - {self._low_path}")

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

    def _set_status(self, msg: str) -> None:
        self._status.setText(msg)
        self.statusBar().showMessage(msg)


def launch(
    low_path: str,
    high_path: str | None = None,
    cage_path: str | None = None,
    hdr_path: str | None = None,
    global_push: float | None = None,
) -> None:
    """Open the Qt application window and run the event loop until the user quits."""
    app = QApplication.instance() or QApplication([])
    win = MainWindow(low_path, high_path, cage_path, hdr_path, global_push)
    win.show()
    app.exec()
