"""CLI entry point.

    python -m cagebakecake [low.usdc] [--high high.usdc] [--cage cage.usdc] [--push 0.03]
    python -m cagebakecake [low.usdc] --screenshot out.png   # headless smoke test

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
    parser.add_argument("--push", type=float, default=0.03, help="initial cage offset")
    parser.add_argument("--screenshot", metavar="PNG", help="render headless to PNG and exit")
    args = parser.parse_args()

    editor = CageEditor(
        args.low,
        high_path=args.high,
        cage_path=args.cage,
        hdr_path=args.hdr,
        global_push=args.push,
        off_screen=bool(args.screenshot),
    )
    if args.screenshot:
        editor.screenshot(args.screenshot)
    else:
        editor.run()


if __name__ == "__main__":
    main()
