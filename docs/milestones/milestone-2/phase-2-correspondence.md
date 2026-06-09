# Phase 2.2 - Correspondence validation

## Goal

Guarantee the cage is a topology-matched duplicate of the low poly before any cage
math runs.

## Tasks

- [ ] Implement `cage.validate_correspondence(lowpoly, cage)` checking
      `len(cage.points) == len(lowpoly.points)`.
- [ ] Call it at load time, before registering actors or enabling editing.
- [ ] On mismatch, surface a clear, actionable error (counts of each, hint about FBX
      vertex splitting) and refuse to proceed rather than producing a wrong cage.
- [ ] Initialize the per-vertex `manual_delta` array to zeros once validation passes.

## Notes

- This check is the guard that lets all downstream math index cage and low poly by
  the same vertex id.
- Reference: `docs/cage-model.md` (correspondence validation, FBX caveat).
