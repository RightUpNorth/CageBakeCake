"""CLI entry point.

    python -m cagebakecake [low.usdc] [--high high.usdc] [--cage cage.usdc] [--push 0.03]
    python -m cagebakecake [low.usdc] --screenshot out.png   # headless smoke test

By default this opens the Qt application window (menu bar + docked controls around the
viewport); --screenshot renders headlessly with a standalone plotter and exits.

Defaults load the Mat Ball low/high pair so the editor opens on a real bake-cage
setup out of the box.
"""

import argparse

from .app import CageEditor


def main() -> None:
    parser = argparse.ArgumentParser(prog="cagebakecake")
    parser.add_argument("low", nargs="?", default="assets/usd/MatBall_LP.usdc",
                        help="low-poly mesh (the cage matches its topology)")
    parser.add_argument("--high", default="assets/usd/MatBall.usdc",
                        help="high-poly reference mesh (shaded, opaque)")
    parser.add_argument("--cage", default=None,
                        help="cage mesh; omit to use an in-memory copy of the low poly")
    parser.add_argument("--hdr", default=None,
                        help="equirectangular HDR/image for lighting; omit for a procedural sky")
    parser.add_argument("--push", type=float, default=None,
                        help="initial cage offset in world units; default is 3%% of the mesh diagonal")
    parser.add_argument("--screenshot", metavar="PNG", help="render headless to PNG and exit")
    parser.add_argument("--no-qt", action="store_true",
                        help="use the standalone pyvista window instead of the Qt front end")
    args = parser.parse_args()

    if args.screenshot:
        editor = CageEditor(
            args.low, high_path=args.high, cage_path=args.cage, hdr_path=args.hdr,
            global_push=args.push, off_screen=True,
        )
        editor.screenshot(args.screenshot)
    elif args.no_qt:
        editor = CageEditor(
            args.low, high_path=args.high, cage_path=args.cage, hdr_path=args.hdr,
            global_push=args.push,
        )
        editor.run()
    else:
        from .window import launch

        launch(
            args.low, high_path=args.high, cage_path=args.cage, hdr_path=args.hdr,
            global_push=args.push,
        )


if __name__ == "__main__":
    main()
