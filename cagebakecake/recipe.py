"""The bake recipe: what maps to bake and how to pack them into exported PNGs.

A recipe is the design handoff's Recipe section as plain data: a list of bake maps
(each a map *type* with a name, plus tangent/object space for normals) and a list of
output files (each one exported PNG, packing baked maps into its R/G/B/A channels).
It is pure, JSON-serializable, and UI-blind - the dock binds widgets to it and the
editor bakes from it; the actual channel compositing is `bake.pack_outputs`.

Map *kinds* mirror the handoff's "+ Add" menu: normal, position, ao, curv, cavity,
thickness, height. Only `BAKEABLE_KINDS` actually produce data today (the cage/bake
pipeline bakes normal, AO and curvature); the others are modeled so recipes round-trip
and the UI is complete, but they pack as empty channels until their bakes exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import theme

# Kinds that the current bake pipeline can actually produce. The rest are modeled
# (so presets and the UI are faithful to the handoff) but pack as empty channels.
BAKEABLE_KINDS = ("normal", "ao", "curv", "height", "position", "thickness")


@dataclass
class BakeMap:
    """One map to bake: a kind, a user-editable display name, and - for normals -
    the encoding space (tangent or object)."""
    id: str
    kind: str
    name: str
    space: str | None = None  # 'tangent' | 'object', only meaningful for kind == 'normal'

    @property
    def channels(self) -> int:
        return theme.channel_count(self.kind)


@dataclass
class Output:
    """One exported PNG. `type` is 'color' (an RGB source + optional alpha) or
    'packed' (four independent single-channel sources). `file` may contain `{LP}`,
    resolved to the low-poly name at pack time. `ch` maps each of r/g/b/a to a
    BakeMap id or None (empty)."""
    id: str
    type: str            # 'color' | 'packed'
    file: str            # without extension; may contain '{LP}'
    ch: dict             # {'r': id|None, 'g': id|None, 'b': id|None, 'a': id|None}


@dataclass
class Recipe:
    name: str
    bake_maps: list[BakeMap] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)

    # --- serialization ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "bake_maps": [vars(m) for m in self.bake_maps],
            "outputs": [vars(o) for o in self.outputs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Recipe":
        return cls(
            name=d.get("name", "Recipe"),
            bake_maps=[BakeMap(**m) for m in d.get("bake_maps", [])],
            outputs=[Output(**o) for o in d.get("outputs", [])],
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "Recipe":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    # --- editing helpers -------------------------------------------------
    def map_by_id(self, map_id: str | None) -> BakeMap | None:
        if map_id is None:
            return None
        return next((m for m in self.bake_maps if m.id == map_id), None)

    def unique_name(self, base: str) -> str:
        """A de-duplicated display name like the handoff: 'Normal', 'Normal 2', ..."""
        names = {m.name for m in self.bake_maps}
        if base not in names:
            return base
        n = 2
        while f"{base} {n}" in names:
            n += 1
        return f"{base} {n}"

    def add_map(self, kind: str) -> BakeMap:
        m = BakeMap(
            id=_new_id("m"),
            kind=kind,
            name=self.unique_name(theme.MAP_LABELS[kind]),
            space="tangent" if kind == "normal" else None,
        )
        self.bake_maps.append(m)
        return m

    def remove_map(self, map_id: str) -> None:
        """Drop a bake map and clear any packing channel that referenced it."""
        self.bake_maps = [m for m in self.bake_maps if m.id != map_id]
        for out in self.outputs:
            for c, ref in out.ch.items():
                if ref == map_id:
                    out.ch[c] = None


# Monotonic id source. Ids only need to be unique within a recipe and stable across
# a session; a plain counter avoids depending on Date/random (unavailable headless).
_counter = 0


def _new_id(prefix: str) -> str:
    global _counter
    _counter += 1
    return f"{prefix}{_counter}"


def _color(file: str, rgb: str, a: str | None = None) -> Output:
    """A color output: one RGB source mirrored across r/g/b, plus optional alpha."""
    return Output(id=_new_id("o"), type="color", file=file,
                  ch={"r": rgb, "g": rgb, "b": rgb, "a": a})


def _packed(file: str, r=None, g=None, b=None, a=None) -> Output:
    return Output(id=_new_id("o"), type="packed", file=file,
                  ch={"r": r, "g": g, "b": b, "a": a})


def presets() -> dict[str, Recipe]:
    """The three handoff presets. Built fresh each call so callers get independent,
    mutable copies (ids are freshly minted, so two presets never share map ids)."""
    out: dict[str, Recipe] = {}

    def normal(space="tangent", name="Normal"):
        return BakeMap(_new_id("m"), "normal", name, space)

    def grey(kind):
        return BakeMap(_new_id("m"), kind, theme.MAP_LABELS[kind])

    # Game-ready: tangent normal + a curv/cavity mask.
    n = normal(); ao = grey("ao"); cu = grey("curv"); cv = grey("cavity")
    out["Game-ready"] = Recipe(
        "Game-ready", [n, ao, cu, cv],
        [_color("{LP}_normal", n.id, ao.id), _packed("{LP}_mask", r=cu.id, g=cv.id)],
    )

    # Hero asset: tangent + object normal, ORM-style packed map.
    n = normal(); on = normal("object", "Obj Normal")
    ao = grey("ao"); cu = grey("curv"); cv = grey("cavity"); th = grey("thickness")
    out["Hero asset"] = Recipe(
        "Hero asset", [n, on, ao, cu, cv, th],
        [_color("{LP}_normal", n.id),
         _packed("{LP}_orm", r=ao.id, g=cu.id, b=cv.id, a=th.id)],
    )

    # AO + Curvature: a single two-channel mask.
    ao = grey("ao"); cu = grey("curv")
    out["AO + Curvature"] = Recipe(
        "AO + Curvature", [ao, cu], [_packed("{LP}_mask", r=ao.id, g=cu.id)],
    )
    return out


def resolve_filename(file: str, lp_name: str) -> str:
    """Expand `{LP}` and add the .png extension: '{LP}_mask' -> 'matball_lp_mask.png'."""
    return f"{file.replace('{LP}', lp_name)}.png"
