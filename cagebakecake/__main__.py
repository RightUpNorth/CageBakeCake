"""CLI entry point.

    python -m cagebakecake [mesh.usdc] [--push 0.03]
    python -m cagebakecake [mesh.usdc] --screenshot out.png   # headless smoke test
"""

import argparse

from .app import CageEditor


def main() -> None:
    parser = argparse.ArgumentParser(prog="cagebakecake")
    parser.add_argument("mesh", nargs="?", default="assets/usd/MatBall.usdc")
    parser.add_argument("--push", type=float, default=0.03, help="initial cage offset")
    parser.add_argument("--screenshot", metavar="PNG", help="render headless to PNG and exit")
    args = parser.parse_args()

    editor = CageEditor(args.mesh, global_push=args.push, off_screen=bool(args.screenshot))
    if args.screenshot:
        editor.screenshot(args.screenshot)
    else:
        editor.run()


if __name__ == "__main__":
    main()
