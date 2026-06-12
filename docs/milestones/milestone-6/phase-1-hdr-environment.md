# Phase 6.1 - HDR environment

## Goal

Load an equirectangular HDR as the environment texture for lighting and reflections.

## Tasks

- [ ] Accept an `--hdr env.hdr` argument in the CLI.
- [ ] Load the `.hdr` (imageio / PyVista) and call
      `Plotter.set_environment_texture(hdr, is_srgb=False)`.
- [ ] Confirm the PBR high poly is lit and reflective from the environment.
- [ ] Fall back to a default 3-point light rig when no HDR is supplied.
- [ ] Handle a missing/unreadable HDR file with a clear error and the fallback rig.

## Notes

- `is_srgb=False` because HDR data is linear.
- Reference: `docs/interaction.md`, `docs/architecture.md`.
