"""Full-application README screenshots: the artist steps and all six themes.

Drives the real Qt window through the workflow (open, push, opacity, ray-miss,
bake) and captures screenshots/app/step*.png plus a theme_* gallery shot per
direction x mood (theme shots are saved at half size). Uses the synthetic demo
pair from tools/make_demo_assets.py - run that first.

Captures go through an X server root grab so the GL viewport is included; on a
headless Linux box run under Xvfb:

    python tools/make_demo_assets.py
    xvfb-run -a -s "-screen 0 1920x1200x24" python tools/make_app_screenshots.py

On a desktop (Windows included) it also works as-is, but keep the window
unobscured while it runs - the grab reads actual screen pixels.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)  # run as a plain script from tools/ without installing
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from qtpy.QtWidgets import QApplication

from cagebakecake import theme
from cagebakecake.window import MainWindow

ASSETS = os.path.join(HERE, "assets", "usd")
OUT = os.path.join(HERE, "screenshots", "app")
os.makedirs(OUT, exist_ok=True)

app = QApplication([])
theme.load_fonts()
win = MainWindow(os.path.join(ASSETS, "demo_lp.usdc"),
                 os.path.join(ASSETS, "demo_hp.usdc"), None, None, None)
win.resize(1680, 1000)
win.show()


def pump(seconds=0.6):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def shot(name, half=False):
    pump(0.8)
    win.editor.pl.render()
    pump(0.3)
    g = win.frameGeometry()
    img = app.primaryScreen().grabWindow(0).copy(g.x(), g.y(), g.width(), g.height())
    if half:  # theme gallery thumbnails - keep the repo light
        from qtpy.QtCore import Qt

        img = img.scaled(img.width() // 2, img.height() // 2,
                         Qt.KeepAspectRatio, Qt.SmoothTransformation)
    img.save(os.path.join(OUT, name))
    print(f"[app] wrote {name}", flush=True)


pump(2.0)
ed = win.editor

# Step 1: the app as it opens - low poly + cage over the high poly.
shot("step1_open.png")

# Step 2: push the whole cage out with the displacement control.
ed.global_push = ed.global_push * 2.2
ed._recompose()
shot("step2_push.png")

# Step 3: cage opacity up so the high poly reads through the envelope.
win._opacity.setValue(70)
shot("step3_opacity.png")

def window_bake():
    """Bake synchronously on the editor (the window's threaded bake races when
    driven headlessly), then refresh the window's Baked Maps strip and status so
    the UI reflects it like a real menu bake."""
    ed._bake(resolution=1024, write=False)
    win._refresh_preview()
    win._set_status("Baked. Toggle 'Normal map' / 'Low poly shaded' to compare.")
    pump(0.5)


# Step 4: a too-tight cage baked -> ray-miss overlay paints the problem areas.
ed.global_push = 0.030
ed._recompose()
window_bake()
ed.set_high_visible(False)
ed.set_low_style(True)
win._miss_overlay.setChecked(True)
shot("step4_raymiss.png")

# Step 5: healthy cage, re-bake, inspect the normal map on the low poly.
win._miss_overlay.setChecked(False)
ed.global_push = ed._diag * 0.03
ed._recompose()
window_bake()
ed.set_low_style(True)
ed.set_normal_map(True)
# Show the fresh normal map in the 2D pane and clear the cage so the result reads.
names = [n for n, _img in win._preview_maps]
for i, n in enumerate(names):
    if "ormal" in n:
        win._preview_pick.setCurrentIndex(i)
        break
for attr in ("cage_actor", "_cage_pts_actor", "_cage_wire_actor"):
    actor = getattr(ed, attr, None)
    if actor is not None:
        actor.SetVisibility(False)
shot("step5_baked.png")

# Hero (the README's first image): the whole story in one frame - the translucent
# cage around the normal-mapped low poly, the baked map in the 2D pane and tray.
for attr in ("cage_actor", "_cage_pts_actor", "_cage_wire_actor"):
    actor = getattr(ed, attr, None)
    if actor is not None:
        actor.SetVisibility(True)
shot("hero.png")

# Theme gallery: two directions x three moods.
for d_idx, d_name in enumerate(theme.DIRECTIONS):
    for m_idx, m_name in enumerate(theme.MOODS):
        win._direction_pick.set_current_index(d_idx)
        win._on_direction(d_idx)
        win._mood_pick.set_current_index(m_idx)
        win._on_mood(m_idx)
        shot(f"theme_{d_name}_{m_name}.png", half=True)

print("[app] done", flush=True)
os._exit(0)  # skip Qt teardown crashes in headless mode
