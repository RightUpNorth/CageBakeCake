# Phase 5.1 - PBR material

## Goal

Apply PyVista PBR to the high poly.

## Tasks

- [ ] Render the high poly with `add_mesh(high, pbr=True, metallic=..., roughness=...,
      smooth_shading=True)`.
- [ ] Choose sensible default metallic/roughness values.
- [ ] Confirm shading looks correct with the default lights (HDR lighting arrives in
      Milestone 6; verify it does not look black/unlit here).
- [ ] Leave low poly (wireframe) and cage (semi-transparent) styling unchanged.

## Notes

- PBR really comes alive once the HDR environment is set in Milestone 6; this phase
  just establishes the material.
