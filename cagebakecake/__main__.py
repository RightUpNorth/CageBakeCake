"""CLI entry point.

    python -m cagebakecake [low.usdc] [--high high.usdc] [--cage cage.usdc] [--push 0.03]
    python -m cagebakecake [low.usdc] --screenshot out.png   # headless smoke test
    python -m cagebakecake [low.usdc] --high high.usdc --bake --maps normal,ao  # headless bake
    python -m cagebakecake --bake-project shot.cbcproj       # headless recipe bake

By default this opens the Qt application window (menu bar + docked controls around the
viewport); --screenshot renders headlessly with a standalone plotter and exits; --bake /
--bake-project run a window-less, GL-free bake and exit.

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
    # Headless batch / CLI bake (no window, no GL).
    parser.add_argument("--bake", action="store_true",
                        help="bake the low/high pair headlessly to PNGs and exit")
    parser.add_argument("--bake-project", metavar="CBCPROJ",
                        help="bake a saved project's recipe headlessly and exit")
    parser.add_argument("--maps", default="normal",
                        help="comma-separated map kinds for --bake: "
                             "normal,objnormal,ao,curv,height,position")
    parser.add_argument("--size", type=int, default=1024, help="--bake map size (square)")
    parser.add_argument("--ss", type=int, default=1, help="--bake supersample multiple")
    parser.add_argument("--padding", type=int, default=0, help="--bake UV-island edge padding")
    parser.add_argument("--ao-samples", type=int, default=64, help="--bake AO rays per texel")
    parser.add_argument("--flip-green", action="store_true",
                        help="--bake: invert normal-map green (DirectX convention)")
    parser.add_argument("--out", default=None, help="output directory for --bake / --bake-project")
    args = parser.parse_args()

    if args.bake_project:
        from . import batch

        written = batch.bake_project(args.bake_project, out_dir=args.out,
                                     progress=lambda m: print(f"[bake] {m}"))
        print(f"baked {len(written)} texture(s)")
    elif args.bake:
        from . import batch

        written = batch.bake_pair(
            args.low, args.high, cage_path=args.cage, out_dir=args.out or ".",
            size=args.size, supersample=args.ss, padding=args.padding, push=args.push,
            ao_samples=args.ao_samples, maps=tuple(args.maps.split(",")),
            flip_green=args.flip_green, progress=lambda m: print(f"[bake] {m}"))
        print(f"baked {len(written)} map(s)")
    elif args.screenshot:
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
