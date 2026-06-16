"""Theme palettes and stylesheet generation for the CageBakeCake UI.

The design handoff (docs/design/design_handoff_bake_recipe) specifies a 6-palette
matrix driven by two independent axes:

- direction: ``A`` = Patisserie, ``B`` = Chocolatier
- mood:      ``light`` / ``neutral`` / ``dark``

The palette key is ``"<direction>-<mood>"`` (e.g. ``A-light``). Every UI color is a
named token; this module encodes the tokens for all six palettes and emits a Qt
stylesheet from them, so the whole window recolors live when the axes change.

The 3D viewport (PyVista/VTK) is not styled by QSS - it reads ``viewport_colors()``,
a small derived set of actor colors per palette, so the viewport recolors with the
panel. Fixed (non-themed) colors from the handoff - the RGBA channel chips, the
bake-map type swatches, and the axis-gizmo colors - live here too as plain
constants so the rest of the code has a single source of truth.
"""

from __future__ import annotations

# --- the six palettes ------------------------------------------------------
# Token values are taken verbatim from the handoff README's palette tables.
# Direction A keeps the soft 18/12px radii; direction B tightens to 11/7px.

_A_LIGHT = {
    "desktop": "#e9d3da", "win": "#fdf6f1", "titlebar": "#f5ccd6",
    "titletext": "#74404f", "menubar": "#fbeef0", "menutext": "#8a5a66",
    "menuhover": "#f3dde2", "panel": "#fdf6f1", "panel2": "#f8e9ed",
    "inset": "#f4dde3", "border": "#eccfd6", "border2": "#e6c2cb",
    "ink": "#5b3742", "inksoft": "#a07b86", "inkfaint": "#c4a4ad",
    "accent": "#df6486", "accent-ink": "#fff7f9", "accent2": "#efb24c",
    "good": "#5aa86e", "warn": "#e08a3c",
}
_A_NEUTRAL = {
    "desktop": "#cfc7b6", "win": "#f3ede1", "titlebar": "#cdbfa4",
    "titletext": "#4c4434", "menubar": "#ece4d6", "menutext": "#6f654f",
    "menuhover": "#e1d7c4", "panel": "#f3ede1", "panel2": "#e9e0cf",
    "inset": "#e3d8c4", "border": "#dbd0bb", "border2": "#cdc0a6",
    "ink": "#43402f", "inksoft": "#857c64", "inkfaint": "#b3a888",
    "accent": "#8a9a63", "accent-ink": "#fbfdf4", "accent2": "#c08a4f",
    "good": "#6f9a52", "warn": "#bc7e3a",
}
_A_DARK = {
    "desktop": "#171110", "win": "#28201c", "titlebar": "#352a22",
    "titletext": "#f0ddc8", "menubar": "#231b17", "menutext": "#bfa48c",
    "menuhover": "#352a22", "panel": "#28201c", "panel2": "#211a16",
    "inset": "#1c1612", "border": "#3a2d24", "border2": "#4a3829",
    "ink": "#f1e3d2", "inksoft": "#b6997f", "inkfaint": "#7a6450",
    "accent": "#e3a24f", "accent-ink": "#26190c", "accent2": "#7faf8c",
    "good": "#7cb084", "warn": "#e3a24f",
}
_B_LIGHT = {
    "desktop": "#ddd2e2", "win": "#f7f1f5", "titlebar": "#d8c2dd",
    "titletext": "#5b3f62", "menubar": "#efe6ef", "menutext": "#7c6184",
    "menuhover": "#ece0ec", "panel": "#f7f1f5", "panel2": "#ece1ec",
    "inset": "#e6d8e6", "border": "#e2d4e5", "border2": "#d6c2da",
    "ink": "#4a3a52", "inksoft": "#8d7b94", "inkfaint": "#bcabc2",
    "accent": "#9a5ca6", "accent-ink": "#fbf6fc", "accent2": "#d88aa0",
    "good": "#5aa080", "warn": "#cf8a52",
}
_B_NEUTRAL = {
    "desktop": "#c3bcc8", "win": "#e8e2e9", "titlebar": "#bcb0c2",
    "titletext": "#423b48", "menubar": "#ded7df", "menutext": "#6e6576",
    "menuhover": "#d2cad4", "panel": "#e8e2e9", "panel2": "#dcd4dd",
    "inset": "#d3cad5", "border": "#cfc6d1", "border2": "#bfb4c2",
    "ink": "#3b3540", "inksoft": "#7a7180", "inkfaint": "#aaa0b0",
    "accent": "#7d6c8c", "accent-ink": "#f8f5fb", "accent2": "#b07a52",
    "good": "#67996f", "warn": "#b07a52",
}
_B_DARK = {
    "desktop": "#120f17", "win": "#221b2a", "titlebar": "#2d2438",
    "titletext": "#ecdff4", "menubar": "#1b1521", "menutext": "#a797b5",
    "menuhover": "#2d2438", "panel": "#221b2a", "panel2": "#1b1521",
    "inset": "#171019", "border": "#352b41", "border2": "#473956",
    "ink": "#ece1f4", "inksoft": "#a695b5", "inkfaint": "#6d5d7e",
    "accent": "#e3a24f", "accent-ink": "#241606", "accent2": "#6fd0d6",
    "good": "#74c9c4", "warn": "#e3a24f",
}

# Direction A: soft corners; Direction B: tighter corners.
_RADII_A = {"radius": "18px", "radius2": "12px"}
_RADII_B = {"radius": "11px", "radius2": "7px"}


def _palette(tokens: dict, radii: dict) -> dict:
    p = dict(tokens)
    p.update(radii)
    return p


PALETTES: dict[str, dict] = {
    "A-light": _palette(_A_LIGHT, _RADII_A),
    "A-neutral": _palette(_A_NEUTRAL, _RADII_A),
    "A-dark": _palette(_A_DARK, _RADII_A),
    "B-light": _palette(_B_LIGHT, _RADII_B),
    "B-neutral": _palette(_B_NEUTRAL, _RADII_B),
    "B-dark": _palette(_B_DARK, _RADII_B),
}

DIRECTIONS = ("A", "B")
MOODS = ("light", "neutral", "dark")
DEFAULT_DIRECTION = "A"
DEFAULT_MOOD = "light"

# Direction also swaps the asset name and the {LP} resolution target (handoff sec.
# "Theming model"). Used by the packing UI's {LP} preview.
LP_NAME = {"A": "matball_lp", "B": "bin_lp"}

# --- fixed (non-themed) colors from the handoff ----------------------------
# RGBA channel chips and bake-map type swatches: explicitly "do NOT theme these".
CHANNEL_COLORS = {"r": "#d8564e", "g": "#5aac5f", "b": "#4b8fe0", "a": "#8b8b93"}
# Mesh-highlight overlay (name-match hover): amber, fixed.
MESH_HIGHLIGHT = "#ffaa26"
MAP_SWATCHES = {
    "normal": "#8a86ff", "position": "#e0608a", "ao": "#8b8b93",
    "curv": "#5aac5f", "cavity": "#6b6b72", "thickness": "#b07a52",
    "height": "#9a9aa2",
}
# Short tags shown on the 20px bake-map swatch.
MAP_TAGS = {
    "normal": "N", "position": "P", "ao": "AO", "curv": "C",
    "cavity": "Cv", "thickness": "Th", "height": "H",
}
# Human labels for the kind pill / type menu.
MAP_LABELS = {
    "normal": "Normal", "position": "Position", "ao": "Ambient Occlusion",
    "curv": "Curvature", "cavity": "Cavity", "thickness": "Thickness",
    "height": "Height",
}
# 3-channel (RGB) map kinds; everything else is single-channel (grey).
RGB_KINDS = ("normal", "position")


def load_fonts() -> None:
    """Best-effort: register any bundled .ttf under assets/fonts/ so the display
    (Bricolage Grotesque) and body (Hanken Grotesk) families named in the QSS
    resolve. If the files are absent (licensing not yet sorted), Qt falls back to
    the next family in each stack - the layout is unaffected."""
    import glob
    import os

    from qtpy.QtGui import QFontDatabase

    here = os.path.dirname(__file__)
    fonts_dir = os.path.join(here, "..", "assets", "fonts")
    for path in glob.glob(os.path.join(fonts_dir, "*.ttf")):
        QFontDatabase.addApplicationFont(path)


def palette_key(direction: str, mood: str) -> str:
    return f"{direction}-{mood}"


# The palette currently applied to the window, so custom-painted widgets (the pill
# toggle switch) can read accent/inset/ink without each holding a copy. window.py
# calls set_active() whenever the theme changes.
_active_key = palette_key(DEFAULT_DIRECTION, DEFAULT_MOOD)


def set_active(key: str) -> None:
    global _active_key
    _active_key = key


def active() -> dict:
    return PALETTES[_active_key]


def channel_count(kind: str) -> int:
    """3 for normal/position (RGB), 1 for the grey maps."""
    return 3 if kind in RGB_KINDS else 1


def viewport_colors(key: str) -> dict:
    """Actor colors for the VTK viewport, derived from the palette so the 3D view
    recolors with the panel. The cage (the editable star of the view) takes the
    accent; its vertex points take the amber accent2; the sky is a vertical
    gradient from a mid tint down to the desktop base."""
    p = PALETTES[key]
    return {
        "cage": p["accent"],
        "cage_points": p["accent2"],
        "cage_wire": p["accent"],
        # A visible vertical sky: light panel up top falling to the darker desktop
        # base (menuhover/desktop were nearly identical and read as a flat fill).
        "sky_top": p["panel"],
        "sky_bottom": p["desktop"],
    }


def build_qss(key: str) -> str:
    """A Qt stylesheet for the given palette key. Tokens are substituted into a
    fixed template; the same template serves all six palettes."""
    p = PALETTES[key]
    return _QSS_TEMPLATE.format(**p)


# The stylesheet template. Doubled braces are literal QSS braces; single-brace
# names are palette tokens substituted by str.format. Headings (section titles,
# the primary button) are tagged with a "heading" property so they can carry the
# display font; everything else uses the body font.
_QSS_TEMPLATE = """
QMainWindow, QWidget {{
    background: {win};
    color: {ink};
    font-family: "Hanken Grotesk", "Segoe UI", sans-serif;
    font-size: 12px;
}}
QDockWidget {{
    titlebar-close-icon: none;
    color: {titletext};
    font-weight: 600;
}}
QDockWidget::title {{
    background: {titlebar};
    color: {titletext};
    padding: 7px 12px;
}}
QDockWidget > QWidget {{ background: {panel}; }}

QMenuBar {{ background: {menubar}; color: {menutext}; padding: 2px; }}
QMenuBar::item {{ background: transparent; padding: 6px 10px; border-radius: {radius2}; }}
QMenuBar::item:selected {{ background: {menuhover}; }}
QMenu {{ background: {panel}; color: {ink}; border: 1px solid {border}; border-radius: {radius2}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {inset}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 6px; }}

QToolBar {{ background: {menubar}; border: none; spacing: 6px; padding: 4px 8px; }}

QStatusBar {{ background: {panel2}; color: {inksoft}; }}
QStatusBar::item {{ border: none; }}

QGroupBox {{
    background: {panel2};
    border: 1px solid {border};
    border-radius: {radius2};
    margin-top: 14px;
    padding: 10px 10px 8px 10px;
    font-weight: 700;
    color: {ink};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {titletext};
}}

QLabel {{ background: transparent; color: {ink}; }}

QToolButton#sectionHeader {{
    background: transparent;
    color: {titletext};
    border: none;
    border-top: 1px solid {border};
    padding: 12px 2px 4px 2px;
    margin-top: 4px;
    font-family: "Bricolage Grotesque", "Segoe UI", sans-serif;
    font-weight: 700;
    font-size: 14px;
    text-align: left;
}}
QToolButton#sectionHeader:hover {{ color: {accent}; }}

QLabel#eyebrow {{ color: {inksoft}; font-weight: 700; font-size: 10px; }}
QLabel#resolved {{ color: {inkfaint}; font-size: 10px; }}
QLabel#helper {{ color: {inksoft}; font-size: 11px; }}
QLabel#fieldcap {{ color: {ink}; font-size: 12px; }}
QLabel#fieldval {{ color: {inksoft}; font-size: 12px; font-weight: 600; }}

QWidget#footer {{ background: {panel2}; border-top: 1px solid {border}; }}

/* Baked Maps tray (Region B). */
QWidget#tray {{ background: {panel2}; border-top: 1px solid {border}; }}
QLabel#trayTitle {{ color: {ink}; font-family: "Bricolage Grotesque","Segoe UI",sans-serif;
    font-weight: 700; font-size: 13px; }}
QLabel#traySize {{ color: {inksoft}; font-size: 11px; }}
QPushButton#tab {{ background: {inset}; color: {inksoft}; border: none; border-radius: 11px;
    padding: 4px 14px; font-size: 11px; font-weight: 600; }}
QPushButton#tab:hover {{ color: {ink}; }}
QPushButton#tab:checked {{ background: {accent}; color: {accent-ink}; }}

QFrame#card {{
    background: {panel2};
    border: 1px solid {border};
    border-radius: 9px;
}}

/* Numbered eyebrow chips (1 BAKE SETTINGS / 2 PACKING). */
QLabel#numAccent {{ background: {accent}; color: {accent-ink}; border-radius: 5px;
    font-size: 9px; font-weight: 700; }}
QLabel#numAccent2 {{ background: {accent2}; color: {accent-ink}; border-radius: 5px;
    font-size: 9px; font-weight: 700; }}

/* Bake-map kind pill. */
QLabel#kindpill {{ background: {inset}; color: {inksoft}; border-radius: 7px;
    padding: 2px 8px; font-size: 9px; font-weight: 600; }}

/* Packing channel cells. */
QFrame#cell {{ background: {panel}; border: 1px solid {border2}; border-radius: 8px; }}
QFrame#cell:hover {{ border-color: {accent}; }}
QToolButton#cellbtn {{ background: transparent; border: none; color: {ink};
    text-align: left; padding: 2px 2px; font-size: 11px; }}
QToolButton {{
    background: {inset};
    color: {ink};
    border: 1px solid {border2};
    border-radius: 7px;
    padding: 4px 8px;
}}
QToolButton:hover {{ border-color: {accent}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* Title bar (the design's 48px themed bar - the real, frameless title bar). */
QWidget#chrome {{ background: {titlebar}; }}
QWidget#titlebar {{ background: {titlebar}; }}
QLabel#appmark {{ background: {accent}; border-radius: 6px; }}
QLabel#apptitle {{ color: {titletext}; font-family: "Bricolage Grotesque","Segoe UI",sans-serif;
    font-weight: 700; font-size: 15px; }}
QLabel#assetname {{ color: {inksoft}; font-size: 12px; }}
QLabel#themelabel {{ color: {inksoft}; font-size: 9px; font-weight: 700; }}
QLabel#caption {{ color: {inkfaint}; font-size: 10px; }}

/* Functional window buttons (minimize / maximize / close). */
QToolButton#winmin, QToolButton#winmax, QToolButton#winclose {{
    border: none; border-radius: 6px; padding: 0; }}
QToolButton#winmin {{ background: {accent2}; }}
QToolButton#winmax {{ background: {good}; }}
QToolButton#winclose {{ background: {accent}; }}
QToolButton#winmin:hover, QToolButton#winmax:hover, QToolButton#winclose:hover {{
    border: 1px solid {titletext}; }}

/* 2D UV pane (design Region A, '2d'/'split'). */
QWidget#uvpane {{ background: {panel2}; border-left: 1px solid {border}; }}
QLabel#uvcaption {{ color: {inksoft}; background: {panel2}; font-size: 10px; padding: 4px; }}

/* Segmented control (Direction / Mood). */
QWidget#segmented {{ background: {inset}; border-radius: 9px; }}
QToolButton#segment {{ background: transparent; border: none; border-radius: 7px;
    padding: 4px 11px; color: {inksoft}; font-size: 11px; font-weight: 600; }}
QToolButton#segment:hover {{ color: {ink}; }}
QToolButton#segment:checked {{ background: {accent}; color: {accent-ink}; }}

/* Three faux window dots. */
QLabel[dot="off"] {{ background: {border2}; border-radius: 6px; min-width: 11px; max-width: 11px;
    min-height: 11px; max-height: 11px; }}
QLabel[dot="on"] {{ background: {accent}; border-radius: 6px; min-width: 11px; max-width: 11px;
    min-height: 11px; max-height: 11px; }}

/* Status bar: a colored status dot + segments. */
QLabel#statusdot {{ background: {good}; border-radius: 4px; min-width: 8px; max-width: 8px;
    min-height: 8px; max-height: 8px; }}
QLabel#statusseg {{ color: {inksoft}; font-size: 11px; }}
QLabel#statusright {{ color: {inksoft}; font-size: 11px; }}

/* Primary "Bake recipe" button — two-line label + a kbd hint. */
QPushButton#primary {{ text-align: left; padding: 12px 14px; }}
QLabel#primarytitle {{ color: {accent-ink}; font-family: "Bricolage Grotesque","Segoe UI",sans-serif;
    font-weight: 700; font-size: 15px; background: transparent; }}
QLabel#primarysub {{ color: {accent-ink}; font-size: 10px; background: transparent; }}
QLabel#kbd {{ color: {accent-ink}; border: 1px solid {accent-ink}; border-radius: 5px;
    padding: 1px 6px; font-size: 10px; font-weight: 700; background: transparent; }}

/* Secondary footer links. */
QPushButton#linkAccent {{ background: transparent; border: none; color: {accent}; font-weight: 600;
    padding: 4px 2px; }}
QPushButton#linkSoft {{ background: transparent; border: none; color: {inksoft}; padding: 4px 2px; }}
QPushButton#linkFaint {{ background: transparent; border: none; color: {inkfaint}; padding: 4px 2px; }}

QFrame#nmRow {{ border-top: 1px solid {border}; }}
QFrame#nmRow:hover {{ background: {inset}; }}
QLabel[glyph="matched"] {{ color: {good}; font-size: 14px; }}
QLabel[glyph="nomatch"] {{ color: {warn}; font-size: 14px; }}
QLabel[glyph="manual"] {{ color: {inkfaint}; font-size: 14px; }}
QLabel[badge="matched"] {{ color: {good}; border: 1px solid {good};
    border-radius: 8px; padding: 1px 6px; font-size: 9px; font-weight: 700; }}
QLabel[badge="nomatch"] {{ color: {warn}; border: 1px solid {warn};
    border-radius: 8px; padding: 1px 6px; font-size: 9px; font-weight: 700; }}
QLabel[badge="manual"] {{ color: {inksoft}; border: 1px solid {border2};
    border-radius: 8px; padding: 1px 6px; font-size: 9px; font-weight: 700; }}

QPushButton {{
    background: {inset};
    color: {ink};
    border: 1px solid {border2};
    border-radius: {radius2};
    padding: 6px 12px;
}}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{ color: {inkfaint}; border-color: {border}; }}

QPushButton#primary {{
    background: {accent};
    color: {accent-ink};
    border: none;
    border-radius: {radius2};
    padding: 10px 14px;
    font-weight: 700;
    font-family: "Bricolage Grotesque", "Segoe UI", sans-serif;
}}
QPushButton#primary:hover {{ background: {accent2}; }}

QCheckBox {{ background: transparent; color: {ink}; spacing: 7px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {border2}; background: {inset}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}

QComboBox {{
    background: {panel};
    color: {ink};
    border: 1px solid {border2};
    border-radius: 8px;
    padding: 5px 8px;
}}
QComboBox:hover {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {inksoft};
    margin-right: 7px;
}}
QComboBox QAbstractItemView {{
    background: {panel};
    color: {ink};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {inset};
    selection-color: {ink};
    outline: none;
}}

QLineEdit {{
    background: transparent;
    color: {ink};
    border: none;
    border-bottom: 1px solid transparent;
    padding: 2px 1px;
}}
QLineEdit:focus {{ border-bottom: 1px dashed {accent}; }}

QListWidget {{
    background: {panel};
    color: {ink};
    border: 1px solid {border};
    border-radius: 8px;
}}
QListWidget::item:selected {{ background: {inset}; color: {ink}; }}

QSlider::groove:horizontal {{
    height: 4px; border-radius: 2px; background: {inset};
}}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 15px; height: 15px; margin: -6px 0; border-radius: 7px;
    background: {panel}; border: 2px solid {accent};
}}
QSlider#amberSlider::sub-page:horizontal {{ background: {accent2}; border-radius: 2px; }}
QSlider#amberSlider::handle:horizontal {{ border: 2px solid {accent2}; }}

QScrollBar:vertical {{ background: {panel}; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border2}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: {panel}; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {border2}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QSplitter::handle {{ background: {border}; }}
QTableWidget, QHeaderView::section {{
    background: {panel};
    color: {ink};
    border: none;
}}
QHeaderView::section {{ background: {inset}; color: {inksoft}; padding: 5px 8px; font-weight: 700; }}
"""
