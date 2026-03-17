"""
strip_unused_decals.py

Removes decals from every .bin map file whose texture does not resolve to an
actual file in Graphics/Atlases/Gameplay/decals/ (mod-local only; vanilla
Celeste decals bundled with the game are in the shipped Gameplay atlas, not on
disk here – those are kept as-is since they are known to be valid).

Strategy
--------
1. Walk Graphics/Atlases/Gameplay/decals/ and build a set of known paths
   (without extension, matching how Celeste stores them in .bin).
2. For each .bin: parse it, drop any decal element whose `texture` is not in
   the known set OR whose path looks obviously corrupted (double-concatenated
   prefix like "maggy/10-Ruinsdecals/maggy/…").
3. Write the cleaned .bin back in-place.

Run from the workspace root:
    python loenn-mcp/strip_unused_decals.py
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from celeste_bin import read_map, write_map, find_child, find_children, get_rooms

WORKSPACE = Path(__file__).parent.parent
DECAL_ROOT = WORKSPACE / "Graphics" / "Atlases" / "Gameplay" / "decals"


def build_available_textures() -> tuple[set[str], set[str]]:
    """
    Return (exact_paths, animation_bases).

    exact_paths: every relative path found under DECAL_ROOT, stored both with
                 and without .png extension.
    animation_bases: base names stripped of the trailing 2-digit frame number,
                     so that `warp_star` matches `warp_star00.png` /
                     `warp_star01.png`.
    """
    exact_paths: set[str] = set()
    animation_bases: set[str] = set()
    for p in DECAL_ROOT.rglob("*.png"):
        rel = str(p.relative_to(DECAL_ROOT)).replace("\\", "/")
        without_ext = rel[:-4]  # strip .png
        exact_paths.add(rel)          # with .png
        exact_paths.add(without_ext)  # without .png
        # Strip trailing frame digits (e.g. "warp_star00" -> "warp_star")
        stem = without_ext
        if len(stem) >= 2 and stem[-2:].isdigit():
            animation_bases.add(stem[:-2])
    return exact_paths, animation_bases


def is_texture_valid(texture: str, available: set[str], anim_bases: set[str]) -> bool:
    """
    A texture is valid if either:
      - it resolves to a known file in our local atlas (exact match, or
        animation-base match where the .png suffix is stripped first), OR
      - it comes from a vanilla Celeste chapter folder that the player's game
        will supply – we trust those paths.
    """
    if not texture:
        return False

    # Local atlas: exact hit (with or without .png)
    if texture in available:
        return True

    # Local atlas: animation-base hit.
    # e.g. "maggy/3_stars/warp_star.png" -> strip .png -> "maggy/3_stars/warp_star"
    # -> check animation_bases for that key.
    stripped = texture[:-4] if texture.endswith(".png") else texture
    if stripped in available or stripped in anim_bases:
        return True

    # Clearly corrupted: path contains the prefix repeated
    if "decals/" in texture:
        return False

    # Vanilla Celeste chapter folders – the game ships these, trust them.
    VANILLA_PREFIXES = (
        "0-prologue/", "1-forsakencity/", "2-oldsite/", "3-resort/",
        "4-cliffside/", "5-temple/", "5-temple-dark/", "6-reflection/",
        "6-stronghold/", "7-summit/", "8-epilogue/", "9-core/",
        "10-farewell/", "generic/",
        # Community decal packs shipped as dependencies:
        "nameguy/", "nameguy_farewell/", "nameguy_farewell_celeste/",
        "monidsidespack_", "monikadsidespack_",
        "LumaCeleste/",
    )
    for prefix in VANILLA_PREFIXES:
        if texture.startswith(prefix):
            return True

    # Anything else that is NOT in our local atlas is suspicious
    return False


def is_texture_corrupted(texture: str) -> bool:
    """Detect obviously corrupted/double-prefix paths."""
    if "decals/" in texture:
        return True
    if "Ruinsdecals" in texture or "Ruinsmaggy" in texture:
        return True
    return False


def clean_map(map_path: Path, available: set[str], anim_bases: set[str]) -> tuple[int, int]:
    """
    Remove invalid decals from a map file.
    Returns (removed_fg, removed_bg).
    """
    data = read_map(map_path)
    removed_fg = 0
    removed_bg = 0

    for room in get_rooms(data):
        for section_name in ("fgdecals", "bgdecals"):
            sec = find_child(room, section_name)
            if sec is None:
                continue
            before = [c for c in sec.get("__children", []) if c.get("__name") == "decal"]
            keep = []
            for decal in before:
                tex = decal.get("texture", "")
                if is_texture_corrupted(tex) or not is_texture_valid(tex, available, anim_bases):
                    if section_name == "fgdecals":
                        removed_fg += 1
                    else:
                        removed_bg += 1
                    print(f"    REMOVE [{section_name}] texture={tex!r}")
                else:
                    keep.append(decal)
            # Rebuild children: non-decal children first, then kept decals
            other_children = [c for c in sec.get("__children", []) if c.get("__name") != "decal"]
            sec["__children"] = other_children + keep

    if removed_fg + removed_bg > 0:
        write_map(map_path, data)

    return removed_fg, removed_bg


def main():
    available, anim_bases = build_available_textures()
    print(f"Known local decal textures: {len(available) // 2} files  ({len(anim_bases)} animation bases)")

    bin_files = sorted(glob.glob(str(WORKSPACE / "Maps" / "Maggy" / "**" / "*.bin"), recursive=True))
    print(f"Processing {len(bin_files)} .bin files...\n")

    total_fg = 0
    total_bg = 0
    modified = 0

    for f in bin_files:
        p = Path(f)
        rel = p.relative_to(WORKSPACE)
        rfg, rbg = clean_map(p, available, anim_bases)
        if rfg + rbg > 0:
            print(f"  {rel}: removed {rfg} FG + {rbg} BG decals")
            modified += 1
            total_fg += rfg
            total_bg += rbg
        else:
            print(f"  {rel}: clean")

    print(f"\nDone. Modified {modified} files.")
    print(f"Removed totals: {total_fg} FG decals, {total_bg} BG decals.")


if __name__ == "__main__":
    main()
