# PyInstaller spec for the Windows alpha build (one-folder mode).
#
# Build:  pyinstaller cagebakecake.spec --noconfirm
# Output: dist/CageBakeCake/ containing CageBakeCake.exe (windowed) and
#         CageBakeCake-console.exe (same app with a console attached, so alpha
#         testers can see tracebacks and use the headless --bake CLI).
#
# One-folder rather than one-file: VTK, PySide6 and USD ship hundreds of
# binaries/plugins; onedir keeps startup fast and plugin resolution sane.

from PyInstaller.utils.hooks import collect_all

# Bundled UI fonts. theme.load_fonts() resolves them relative to the package
# (../assets/fonts), which lands inside the bundle, so no code change is needed.
datas = [("assets/fonts", "assets/fonts")]
binaries = []
hiddenimports = []

# Packages whose data/plugins PyInstaller's stock hooks don't fully cover:
# - pxr (usd-core): plugInfo.json plugin registry files must ship or Usd.Stage
#   cannot open anything.
# - embreex: the embree BVH backend trimesh discovers dynamically.
for pkg in ("pxr", "embreex"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["launcher.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter"],
)

pyz = PYZ(a.pure)

exe_gui = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="CageBakeCake",
    console=False,
)

exe_console = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="CageBakeCake-console",
    console=True,
)

coll = COLLECT(
    exe_gui,
    exe_console,
    a.binaries,
    a.datas,
    name="CageBakeCake",
)
