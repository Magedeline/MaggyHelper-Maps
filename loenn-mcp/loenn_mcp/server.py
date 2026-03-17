"""
Lönn MCP Server — Celeste Map Editor for AI Agents

Provides tools for reading, editing, analyzing, and generating Celeste map
files (.bin) directly from VS Code via the Model Context Protocol.

Tools:
  Map Reading:    list_maps, read_map_overview, read_room, get_room_tiles
  Map Editing:    add_entity, remove_entity, set_room_tiles, add_room,
                                    remove_room, create_map, generate_starter_map
  Entity Catalog: list_entity_definitions, get_entity_definition,
                  list_trigger_definitions
  Analysis:       analyze_map, visualize_map_layout

Usage:
  python server.py                         (uses cwd as workspace)
  LOENN_MCP_WORKSPACE=/path python server.py  (explicit workspace)
"""

import json
import os
import re
import sys
import textwrap
from pathlib import Path

from fastmcp import FastMCP

try:
    from . import celeste_bin as cb          # installed package
except ImportError:
    import celeste_bin as cb                 # run directly from source

WORKSPACE = Path(os.environ.get("LOENN_MCP_WORKSPACE", ".")).resolve()

mcp = FastMCP(
    "loenn-mcp",
    instructions=(
        "Celeste / Lönn Map Editor MCP — read, edit, and analyze "
        "Celeste .bin map files and browse Lönn entity definitions"
    ),
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve(map_path: str) -> Path:
    """Resolve a map path relative to the workspace, with path-traversal guard."""
    p = Path(map_path)
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    # Use is_relative_to (Python 3.9+) for a watertight boundary check.
    # startswith("/foo/bar") would incorrectly pass "/foo/bar-evil/".
    try:
        p.relative_to(WORKSPACE)
    except ValueError:
        raise ValueError("Path must be within the workspace")
    return p


def _room_names(map_data: dict) -> str:
    return ", ".join(r.get("name", "?") for r in cb.get_rooms(map_data))


def _next_entity_id(room: dict) -> int:
    """Return the next safe entity ID, unique within this room (entities + triggers)."""
    ids: list[int] = []
    for section in ("entities", "triggers"):
        el = cb.find_child(room, section)
        if el:
            for e in el.get("__children", []):
                eid = e.get("id")
                if isinstance(eid, int):
                    ids.append(eid)
    return max(ids, default=0) + 1


_MARKER_TO_ENTITY = {
    "P": "player",
    "R": "strawberry",
    "Q": "refill",
    "C": "checkpoint",
}


def _clean_layout(layout: str) -> list[str]:
    """Normalize multiline ASCII layout text into a list of rows."""
    dedented = textwrap.dedent(layout)
    lines = dedented.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _layout_to_fg_tiles(layout: str) -> tuple[str, list[tuple[str, int, int]], int, int]:
    """Convert ASCII room layout into FG tile text and marker positions."""
    rows = _clean_layout(layout)
    if not rows:
        raise ValueError("Layout must contain at least one non-empty row")

    width_tiles = max(len(row) for row in rows)
    fg_rows: list[str] = []
    markers: list[tuple[str, int, int]] = []

    for y, row in enumerate(rows):
        padded = row.ljust(width_tiles)
        out_chars: list[str] = []
        for x, ch in enumerate(padded):
            if ch in _MARKER_TO_ENTITY:
                markers.append((ch, x, y))
                out_chars.append("0")
            elif ch == " ":
                out_chars.append("0")
            else:
                out_chars.append(ch)
        fg_rows.append("".join(out_chars))

    fg_tiles = "\n".join(fg_rows)
    return fg_tiles, markers, width_tiles, len(rows)


def _empty_obj_tiles(width_tiles: int, height_tiles: int) -> str:
    row = ",".join(["-1"] * width_tiles)
    return "\n".join([row] * height_tiles)


def _remap_solid_chars(tile_text: str, solid_char: str) -> str:
    if not solid_char:
        return tile_text
    rows = tile_text.split("\n")
    return "\n".join(
        "".join(solid_char if ch != "0" else "0" for ch in row)
        for row in rows
    )


def _build_background_from_fg(tile_text: str, background_char: str) -> str:
    if not background_char:
        rows = tile_text.split("\n")
        return "\n".join("0" * len(row) for row in rows)
    rows = tile_text.split("\n")
    return "\n".join(
        "".join(background_char if ch != "0" else "0" for ch in row)
        for row in rows
    )


def _normalize_entity_like(item: dict, next_id: int) -> dict:
    name = item.get("name") or item.get("_name") or item.get("__name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Custom entity/trigger entries need a non-empty name")

    result = {
        "__name": name.strip(),
        "__children": [],
        "id": int(item.get("id", next_id)),
        "x": int(item.get("x", 0)),
        "y": int(item.get("y", 0)),
    }
    if "width" in item:
        result["width"] = int(item.get("width", 0))
    if "height" in item:
        result["height"] = int(item.get("height", 0))

    for key, value in item.items():
        if key in {"name", "_name", "__name", "__children", "id", "x", "y", "width", "height"}:
            continue
        if key == "nodes" and isinstance(value, list):
            result["nodes"] = [
                {"x": int(node.get("x", 0)), "y": int(node.get("y", 0))}
                for node in value
                if isinstance(node, dict)
            ]
            continue
        result[key] = value

    return result


def _normalize_decal(item: dict) -> dict:
    texture = item.get("texture") or item.get("path")
    if not isinstance(texture, str) or not texture.strip():
        raise ValueError("Custom decal entries need a non-empty texture")
    return {
        "__name": "decal",
        "__children": [],
        "texture": texture.strip(),
        "x": int(item.get("x", 0)),
        "y": int(item.get("y", 0)),
        "scaleX": float(item.get("scaleX", 1.0)),
        "scaleY": float(item.get("scaleY", 1.0)),
        "rotation": float(item.get("rotation", 0)),
    }


def _normalize_styleground(item: dict) -> dict:
    name = item.get("name") or item.get("_name") or item.get("__name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Styleground entries need a non-empty name")
    effect = {"__name": name.strip(), "__children": []}
    for key, value in item.items():
        if key in {"name", "_name", "__name", "__children"}:
            continue
        effect[key] = value
    return effect


def _apply_stylegrounds(map_data: dict, stylegrounds: dict) -> None:
    if not stylegrounds:
        return
    style = cb.find_child(map_data, "Style")
    if style is None:
        return

    fg = cb.find_child(style, "Foregrounds")
    bg = cb.find_child(style, "Backgrounds")
    if fg is None or bg is None:
        return

    for item in stylegrounds.get("foregrounds", []):
        if isinstance(item, dict):
            fg["__children"].append(_normalize_styleground(item))
    for item in stylegrounds.get("backgrounds", []):
        if isinstance(item, dict):
            bg["__children"].append(_normalize_styleground(item))


def _build_room_from_layout(room_name: str, x: int, y: int, layout: str, spec: dict | None = None) -> dict:
    """Build a complete Celeste room element from an ASCII layout."""
    spec = spec or {}
    name = room_name if room_name.startswith("lvl_") else f"lvl_{room_name}"
    fg_tiles, markers, width_tiles, height_tiles = _layout_to_fg_tiles(layout)
    fg_tiles = _remap_solid_chars(fg_tiles, str(spec.get("solid_char", ""))[:1])
    bg_tiles = _build_background_from_fg(fg_tiles, str(spec.get("background_char", ""))[:1])
    obj_tiles = _empty_obj_tiles(width_tiles, height_tiles)

    entities: list[dict] = []
    next_id = 1
    for marker, tx, ty in markers:
        entity_name = _MARKER_TO_ENTITY.get(marker)
        if entity_name is None:
            continue
        entities.append(
            {
                "__name": entity_name,
                "__children": [],
                "id": next_id,
                "x": tx * 8 + 4,
                "y": ty * 8 + 4,
            }
        )
        next_id += 1

    if not any(e.get("__name") == "player" for e in entities):
        entities.insert(
            0,
            {
                "__name": "player",
                "__children": [],
                "id": next_id,
                "x": 16,
                "y": max(16, height_tiles * 8 - 16),
            },
        )

    next_id = max((int(e.get("id", 0)) for e in entities), default=0) + 1
    extra_entities = []
    for item in spec.get("entities", []):
        if not isinstance(item, dict):
            continue
        entity = _normalize_entity_like(item, next_id)
        next_id = max(next_id, int(entity.get("id", 0)) + 1)
        extra_entities.append(entity)

    triggers = []
    for item in spec.get("triggers", []):
        if not isinstance(item, dict):
            continue
        trigger = _normalize_entity_like(item, next_id)
        next_id = max(next_id, int(trigger.get("id", 0)) + 1)
        triggers.append(trigger)

    fgdecals = []
    for item in spec.get("fgdecals", []):
        if isinstance(item, dict):
            fgdecals.append(_normalize_decal(item))

    bgdecals = []
    for item in spec.get("bgdecals", []):
        if isinstance(item, dict):
            bgdecals.append(_normalize_decal(item))

    room = {
        "__name": "level",
        "name": name,
        "x": x,
        "y": y,
        "width": width_tiles * 8,
        "height": height_tiles * 8,
        "music": "",
        "alt_music": "",
        "ambience": "",
        "dark": False,
        "space": False,
        "underwater": False,
        "whisper": False,
        "disableDownTransition": False,
        "windPattern": "None",
        "musicLayer1": True,
        "musicLayer2": True,
        "musicLayer3": True,
        "musicLayer4": True,
        "musicProgress": "",
        "ambienceProgress": "",
        "cameraOffsetX": 0,
        "cameraOffsetY": 0,
        "delayAltMusicFade": False,
        "c": 0,
        "__children": [
            {"__name": "solids", "innerText": fg_tiles, "offsetX": 0, "offsetY": 0, "__children": []},
            {"__name": "bg", "innerText": bg_tiles, "offsetX": 0, "offsetY": 0, "__children": []},
            {"__name": "objtiles", "innerText": obj_tiles, "offsetX": 0, "offsetY": 0, "tileset": str(spec.get("objtiles_tileset", "scenery")), "__children": []},
            {"__name": "fgtiles", "innerText": str(spec.get("fgtiles", obj_tiles)), "offsetX": 0, "offsetY": 0, "tileset": str(spec.get("fgtiles_tileset", "scenery")), "__children": []},
            {"__name": "bgtiles", "innerText": str(spec.get("bgtiles", obj_tiles)), "offsetX": 0, "offsetY": 0, "tileset": str(spec.get("bgtiles_tileset", "scenery")), "__children": []},
            {"__name": "entities", "__children": entities + extra_entities},
            {"__name": "triggers", "__children": triggers},
            {"__name": "fgdecals", "__children": fgdecals},
            {"__name": "bgdecals", "__children": bgdecals},
        ],
    }

    for key in (
        "music", "alt_music", "ambience", "dark", "space", "underwater", "whisper",
        "disableDownTransition", "windPattern", "musicLayer1", "musicLayer2", "musicLayer3",
        "musicLayer4", "musicProgress", "ambienceProgress", "cameraOffsetX", "cameraOffsetY",
        "delayAltMusicFade", "c",
    ):
        if key in spec:
            room[key] = spec[key]

    return room


def _starter_room_specs(template: str) -> list[dict]:
    """Return room specs for built-in starter templates."""
    if template == "minimal":
        return [
            {
                "name": "start",
                "x": 0,
                "y": 0,
                "layout": """
3333333333333333
3              3
3              3
3              3
3              3
3              3
3P             3
3333333333333333
""",
            }
        ]

    if template == "entity":
        return [
            {
                "name": "entity_start",
                "x": 0,
                "y": 0,
                "layout": """
3333333333333333
3              3
3      R       3
3              3
3   Q          3
3              3
3P             3
3333333333333333
""",
            }
        ]

    if template == "route":
        return [
            {
                "name": "route_start",
                "x": 0,
                "y": 0,
                "layout": """
3333333333333333
3              3
3              3
3               
3   Q           
3              3
3P             3
3333333333333333
""",
            },
            {
                "name": "route_berry",
                "x": 128,
                "y": 0,
                "layout": """
3333333333333333
3              3
3              3
               3
3          R   3
3              3
3              3
3333333333333333
""",
            },
        ]

    raise ValueError("Template must be one of: minimal, entity, route")


def _custom_room_specs(custom_rooms_json: str) -> tuple[list[dict], dict]:
    """Parse and normalize custom room specs from a JSON string."""
    try:
        parsed = json.loads(custom_rooms_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid custom_rooms_json: {exc}") from exc

    stylegrounds: dict = {"foregrounds": [], "backgrounds": []}
    if isinstance(parsed, dict):
        style_src = parsed.get("stylegrounds", {})
        if isinstance(style_src, dict):
            stylegrounds = {
                "foregrounds": list(style_src.get("foregrounds", [])),
                "backgrounds": list(style_src.get("backgrounds", [])),
            }
        parsed = parsed.get("rooms")

    if not isinstance(parsed, list) or not parsed:
        raise ValueError("custom_rooms_json must be a non-empty JSON array or object with a non-empty 'rooms' array")

    specs: list[dict] = []
    cursor_x = 0
    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"custom room at index {idx} must be an object")

        name = item.get("name")
        layout = item.get("layout")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"custom room at index {idx} needs a non-empty 'name'")
        if not isinstance(layout, str) or not layout.strip():
            raise ValueError(f"custom room '{name}' needs a non-empty 'layout'")

        _, _, width_tiles, _ = _layout_to_fg_tiles(layout)
        x_raw = item.get("x")
        y_raw = item.get("y")
        x = cursor_x if x_raw is None else int(x_raw)
        y = 0 if y_raw is None else int(y_raw)

        spec = dict(item)
        spec.update({"name": name.strip(), "x": x, "y": y, "layout": layout})
        specs.append(spec)
        cursor_x = x + width_tiles * 8

    return specs, stylegrounds


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def _get_or_create_section(room: dict, name: str) -> dict:
    section = cb.find_child(room, name)
    if section is not None:
        return section
    section = {"__name": name, "__children": []}
    room.setdefault("__children", []).append(section)
    return section


def _add_teleport_trigger(
    room: dict,
    x: int,
    y: int,
    width: int,
    height: int,
    target_room: str,
    target_x: int,
    target_y: int,
) -> None:
    """Append a MaggyHelper teleport trigger to a room."""
    room_w = int(room.get("width", 0))
    room_h = int(room.get("height", 0))

    tx = _clamp(int(x), 0, max(0, room_w - max(1, width)))
    ty = _clamp(int(y), 0, max(0, room_h - max(1, height)))

    trigger = {
        "__name": "MaggyHelper/TeleportTrigger",
        "__children": [],
        "id": _next_entity_id(room),
        "x": tx,
        "y": ty,
        "width": max(1, int(width)),
        "height": max(1, int(height)),
        "targetRoom": target_room,
        "targetX": max(0, int(target_x)),
        "targetY": max(0, int(target_y)),
        "showEffect": False,
    }

    _get_or_create_section(room, "triggers")["__children"].append(trigger)


def _auto_connect_rooms_with_teleports(rooms: list[dict]) -> int:
    """Create bidirectional teleport triggers for touching room edges."""
    links = 0
    n = len(rooms)
    for i in range(n):
        a = rooms[i]
        ax = int(a.get("x", 0))
        ay = int(a.get("y", 0))
        aw = int(a.get("width", 0))
        ah = int(a.get("height", 0))
        a_name = str(a.get("name", ""))

        for j in range(i + 1, n):
            b = rooms[j]
            bx = int(b.get("x", 0))
            by = int(b.get("y", 0))
            bw = int(b.get("width", 0))
            bh = int(b.get("height", 0))
            b_name = str(b.get("name", ""))

            # Horizontal neighbors: right edge of one touches left edge of the other.
            if ax + aw == bx or bx + bw == ax:
                overlap_top = max(ay, by)
                overlap_bottom = min(ay + ah, by + bh)
                if overlap_bottom - overlap_top >= 8:
                    overlap_mid = (overlap_top + overlap_bottom) // 2
                    if ax + aw == bx:
                        _add_teleport_trigger(
                            a,
                            x=aw - 8,
                            y=overlap_mid - ay - 4,
                            width=8,
                            height=8,
                            target_room=b_name,
                            target_x=8,
                            target_y=overlap_mid - by,
                        )
                        _add_teleport_trigger(
                            b,
                            x=0,
                            y=overlap_mid - by - 4,
                            width=8,
                            height=8,
                            target_room=a_name,
                            target_x=max(0, aw - 12),
                            target_y=overlap_mid - ay,
                        )
                    else:
                        _add_teleport_trigger(
                            b,
                            x=bw - 8,
                            y=overlap_mid - by - 4,
                            width=8,
                            height=8,
                            target_room=a_name,
                            target_x=8,
                            target_y=overlap_mid - ay,
                        )
                        _add_teleport_trigger(
                            a,
                            x=0,
                            y=overlap_mid - ay - 4,
                            width=8,
                            height=8,
                            target_room=b_name,
                            target_x=max(0, bw - 12),
                            target_y=overlap_mid - by,
                        )
                    links += 1
                    continue

            # Vertical neighbors: bottom edge of one touches top edge of the other.
            if ay + ah == by or by + bh == ay:
                overlap_left = max(ax, bx)
                overlap_right = min(ax + aw, bx + bw)
                if overlap_right - overlap_left >= 8:
                    overlap_mid = (overlap_left + overlap_right) // 2
                    if ay + ah == by:
                        _add_teleport_trigger(
                            a,
                            x=overlap_mid - ax - 4,
                            y=ah - 8,
                            width=8,
                            height=8,
                            target_room=b_name,
                            target_x=overlap_mid - bx,
                            target_y=8,
                        )
                        _add_teleport_trigger(
                            b,
                            x=overlap_mid - bx - 4,
                            y=0,
                            width=8,
                            height=8,
                            target_room=a_name,
                            target_x=overlap_mid - ax,
                            target_y=max(0, ah - 12),
                        )
                    else:
                        _add_teleport_trigger(
                            b,
                            x=overlap_mid - bx - 4,
                            y=bh - 8,
                            width=8,
                            height=8,
                            target_room=a_name,
                            target_x=overlap_mid - ax,
                            target_y=8,
                        )
                        _add_teleport_trigger(
                            a,
                            x=overlap_mid - ax - 4,
                            y=0,
                            width=8,
                            height=8,
                            target_room=b_name,
                            target_x=overlap_mid - bx,
                            target_y=max(0, bh - 12),
                        )
                    links += 1

    return links


# ═══════════════════════════════════════════════════════════════════════════════
#  MAP READING TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_maps(subdir: str = "Maps") -> str:
    """List all .bin map files in the project.

    Args:
        subdir: Subdirectory to search (default: "Maps")
    """
    maps_dir = (WORKSPACE / subdir).resolve()
    try:
        maps_dir.relative_to(WORKSPACE)
    except ValueError:
        return "Invalid subdir: path must be within the workspace"

    if not maps_dir.exists():
        return f"Directory not found: {subdir}"

    bins = sorted(maps_dir.rglob("*.bin"))
    if not bins:
        return "No .bin map files found."

    lines = [f"Found {len(bins)} map files:"]
    for b in bins:
        rel = b.relative_to(WORKSPACE)
        size_kb = b.stat().st_size / 1024
        lines.append(f"  {rel}  ({size_kb:.1f} KB)")
    return "\n".join(lines)


@mcp.tool()
def read_map_overview(map_path: str) -> str:
    """Parse a .bin map file and return a summary of rooms and structure.

    Args:
        map_path: Path to the .bin file (relative to workspace or absolute)
    """
    path = _resolve(map_path)
    if not path.exists():
        return f"File not found: {map_path}"

    data = cb.read_map(path)
    rooms = cb.get_rooms(data)

    lines = [
        f"Map: {data.get('_package', '?')}",
        f"Rooms: {len(rooms)}",
        "",
        "Room list:",
    ]

    for room in rooms:
        name = room.get("name", "?")
        x, y = room.get("x", 0), room.get("y", 0)
        w, h = room.get("width", 0), room.get("height", 0)

        entities_el = cb.find_child(room, "entities")
        ent_n = len(entities_el.get("__children", [])) if entities_el else 0

        triggers_el = cb.find_child(room, "triggers")
        trig_n = len(triggers_el.get("__children", [])) if triggers_el else 0

        lines.append(
            f"  {name}: pos=({x},{y}) size={w}x{h} "
            f"entities={ent_n} triggers={trig_n}"
        )

    style = cb.find_child(data, "Style")
    if style:
        fg = cb.find_child(style, "Foregrounds")
        bg = cb.find_child(style, "Backgrounds")
        fg_n = len(fg.get("__children", [])) if fg else 0
        bg_n = len(bg.get("__children", [])) if bg else 0
        lines.append(f"\nStylegrounds: {fg_n} foreground, {bg_n} background")

    return "\n".join(lines)


@mcp.tool()
def read_room(map_path: str, room_name: str) -> str:
    """Get detailed data for a specific room: tiles, entities, triggers.

    Args:
        map_path: Path to the .bin file
        room_name: Room name (with or without 'lvl_' prefix)
    """
    path = _resolve(map_path)
    data = cb.read_map(path)
    room = cb.get_room(data, room_name)

    if room is None:
        return f"Room '{room_name}' not found. Available: {_room_names(data)}"

    lines = [
        f"Room: {room.get('name')}",
        f"Position: ({room.get('x', 0)}, {room.get('y', 0)})",
        f"Size: {room.get('width', 0)}x{room.get('height', 0)} px",
        f"Dark: {room.get('dark', False)}, Space: {room.get('space', False)}",
        f"Music: {room.get('music', '')!r}",
        f"Wind: {room.get('windPattern', 'None')}",
    ]

    # Entities
    ent_el = cb.find_child(room, "entities")
    if ent_el:
        ents = ent_el.get("__children", [])
        lines.append(f"\nEntities ({len(ents)}):")
        for e in ents:
            extra = {
                k: v
                for k, v in e.items()
                if k not in ("__name", "__children", "id", "x", "y")
            }
            extra_s = " ".join(f"{k}={v}" for k, v in extra.items())
            lines.append(
                f"  [{e.get('id', 0)}] {e.get('__name', '?')} "
                f"({e.get('x', 0)},{e.get('y', 0)}) {extra_s}".rstrip()
            )

    # Triggers
    trig_el = cb.find_child(room, "triggers")
    if trig_el:
        trigs = trig_el.get("__children", [])
        lines.append(f"\nTriggers ({len(trigs)}):")
        for t in trigs:
            lines.append(
                f"  [{t.get('id', 0)}] {t.get('__name', '?')} "
                f"({t.get('x', 0)},{t.get('y', 0)}) "
                f"{t.get('width', 0)}x{t.get('height', 0)}"
            )

    # Decals
    for layer in ("fgdecals", "bgdecals"):
        dec_el = cb.find_child(room, layer)
        if dec_el:
            decs = dec_el.get("__children", [])
            if decs:
                lines.append(f"\n{layer} ({len(decs)}):")
                for d in decs[:10]:
                    lines.append(
                        f"  {d.get('texture', '?')} "
                        f"({d.get('x', 0)},{d.get('y', 0)}) "
                        f"scale=({d.get('scaleX', 1)},{d.get('scaleY', 1)})"
                    )
                if len(decs) > 10:
                    lines.append(f"  ... and {len(decs) - 10} more")

    # Tile preview
    solids = cb.find_child(room, "solids")
    if solids:
        tiles = solids.get("innerText", "")
        tile_lines = tiles.split("\n")[:20]
        lines.append(f"\nFG tiles (first {len(tile_lines)} rows):")
        for tl in tile_lines:
            lines.append(f"  {tl}")

    return "\n".join(lines)


@mcp.tool()
def get_room_tiles(map_path: str, room_name: str, layer: str = "fg") -> str:
    """Get the complete tile grid for a room as text.

    Args:
        map_path: Path to the .bin file
        room_name: Room name
        layer: "fg" for foreground (solids), "bg" for background
    """
    path = _resolve(map_path)
    data = cb.read_map(path)
    room = cb.get_room(data, room_name)

    if room is None:
        return f"Room '{room_name}' not found."

    child_name = "solids" if layer == "fg" else "bg"
    tiles_el = cb.find_child(room, child_name)

    if tiles_el is None:
        return f"No {layer} tiles in this room."

    tiles = tiles_el.get("innerText", "")
    tw = room.get("width", 0) // 8
    th = room.get("height", 0) // 8
    return f"Layer: {layer} ({tw}x{th} tiles)\n{tiles}"


# ═══════════════════════════════════════════════════════════════════════════════
#  MAP EDITING TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def add_entity(
    map_path: str,
    room_name: str,
    entity_name: str,
    x: int,
    y: int,
    entity_id: int = -1,
    width: int = 0,
    height: int = 0,
    properties: str = "{}",
) -> str:
    """Add an entity to a room and save the map.

    Args:
        map_path: Path to the .bin file
        room_name: Room name
        entity_name: Entity type (e.g. "player", "MaggyHelper/KirbyBoss")
        x: X position in pixels
        y: Y position in pixels
        entity_id: Entity ID (-1 to auto-assign)
        width: Entity width (0 if inapplicable)
        height: Entity height (0 if inapplicable)
        properties: JSON object string of extra properties
    """
    path = _resolve(map_path)
    data = cb.read_map(path)
    room = cb.get_room(data, room_name)

    if room is None:
        return f"Room '{room_name}' not found. Available: {_room_names(data)}"

    ent_el = cb.find_child(room, "entities")
    if ent_el is None:
        ent_el = {"__name": "entities", "__children": []}
        room["__children"].append(ent_el)

    if entity_id < 0:
        entity_id = _next_entity_id(room)

    try:
        props = json.loads(properties)
    except json.JSONDecodeError:
        return f"Invalid JSON properties: {properties}"

    entity: dict = {
        "__name": entity_name,
        "__children": [],
        "id": entity_id,
        "x": x,
        "y": y,
    }
    if width > 0:
        entity["width"] = width
    if height > 0:
        entity["height"] = height
    # Guard: never let user-supplied props overwrite structural keys
    _protected = frozenset(("__name", "__children", "id", "x", "y", "width", "height"))
    entity.update({k: v for k, v in props.items() if k not in _protected})

    ent_el["__children"].append(entity)
    cb.write_map(path, data)

    return (
        f"Added '{entity_name}' (id={entity_id}) at ({x},{y}) "
        f"to room '{room_name}'."
    )


@mcp.tool()
def remove_entity(map_path: str, room_name: str, entity_id: int) -> str:
    """Remove an entity from a room by its ID.

    Args:
        map_path: Path to the .bin file
        room_name: Room name
        entity_id: Entity ID to remove
    """
    path = _resolve(map_path)
    data = cb.read_map(path)
    room = cb.get_room(data, room_name)

    if room is None:
        return f"Room '{room_name}' not found."

    ent_el = cb.find_child(room, "entities")
    if ent_el is None:
        return "No entities in this room."

    children = ent_el.get("__children", [])
    before = len(children)
    ent_el["__children"] = [e for e in children if e.get("id") != entity_id]

    if len(ent_el["__children"]) == before:
        return f"Entity id={entity_id} not found."

    cb.write_map(path, data)
    return f"Removed entity id={entity_id} from '{room_name}'."


@mcp.tool()
def set_room_tiles(
    map_path: str,
    room_name: str,
    tiles: str,
    layer: str = "fg",
) -> str:
    """Set tile data for a room. Each row is a line of characters ('0'=air).

    Args:
        map_path: Path to the .bin file
        room_name: Room name
        tiles: Tile data (newline-separated rows, 1 char per tile)
        layer: "fg" for foreground (solids), "bg" for background
    """
    path = _resolve(map_path)
    data = cb.read_map(path)
    room = cb.get_room(data, room_name)

    if room is None:
        return f"Room '{room_name}' not found."

    child_name = "solids" if layer == "fg" else "bg"
    tiles_el = cb.find_child(room, child_name)

    if tiles_el is None:
        tiles_el = {
            "__name": child_name,
            "__children": [],
            "offsetX": 0,
            "offsetY": 0,
        }
        room["__children"].append(tiles_el)

    tiles_el["innerText"] = tiles.strip()
    cb.write_map(path, data)

    row_count = len(tiles.strip().split("\n"))
    return f"Set {layer} tiles for '{room_name}': {row_count} rows."


@mcp.tool()
def add_room(
    map_path: str,
    room_name: str,
    x: int = 0,
    y: int = 0,
    width: int = 320,
    height: int = 184,
    dark: bool = False,
    space: bool = False,
) -> str:
    """Add a new empty room to a map.

    Args:
        map_path: Path to the .bin file
        room_name: Room name (prefixed with 'lvl_' if needed)
        x: Room X position in pixels
        y: Room Y position in pixels
        width: Room width in pixels (multiple of 8)
        height: Room height in pixels (multiple of 8)
        dark: Whether the room is dark
        space: Whether the room has space physics
    """
    path = _resolve(map_path)
    data = cb.read_map(path)

    levels = cb.find_child(data, "levels")
    if levels is None:
        return "Invalid map: no 'levels' element."

    name = room_name if room_name.startswith("lvl_") else f"lvl_{room_name}"

    for r in cb.get_rooms(data):
        if r.get("name") == name:
            return f"Room '{name}' already exists."

    tw, th = width // 8, height // 8
    air_row = "0" * tw
    fg_tiles = "\n".join([air_row] * th)
    obj_row = ",".join(["-1"] * tw)
    obj_tiles = "\n".join([obj_row] * th)

    room: dict = {
        "__name": "level",
        "name": name,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "music": "",
        "alt_music": "",
        "ambience": "",
        "dark": dark,
        "space": space,
        "underwater": False,
        "whisper": False,
        "disableDownTransition": False,
        "windPattern": "None",
        "musicLayer1": True,
        "musicLayer2": True,
        "musicLayer3": True,
        "musicLayer4": True,
        "musicProgress": "",
        "ambienceProgress": "",
        "cameraOffsetX": 0,
        "cameraOffsetY": 0,
        "delayAltMusicFade": False,
        "c": 0,
        "__children": [
            {"__name": "solids", "innerText": fg_tiles, "offsetX": 0, "offsetY": 0, "__children": []},
            {"__name": "bg", "innerText": fg_tiles, "offsetX": 0, "offsetY": 0, "__children": []},
            {"__name": "objtiles", "innerText": obj_tiles, "offsetX": 0, "offsetY": 0, "tileset": "scenery", "__children": []},
            {"__name": "fgtiles", "innerText": obj_tiles, "offsetX": 0, "offsetY": 0, "tileset": "scenery", "__children": []},
            {"__name": "bgtiles", "innerText": obj_tiles, "offsetX": 0, "offsetY": 0, "tileset": "scenery", "__children": []},
            {"__name": "entities", "__children": []},
            {"__name": "triggers", "__children": []},
            {"__name": "fgdecals", "__children": []},
            {"__name": "bgdecals", "__children": []},
        ],
    }

    levels["__children"].append(room)
    cb.write_map(path, data)

    return f"Added room '{name}' at ({x},{y}) {width}x{height}."


@mcp.tool()
def remove_room(map_path: str, room_name: str) -> str:
    """Remove a room from a map.

    Args:
        map_path: Path to the .bin file
        room_name: Room name to remove
    """
    path = _resolve(map_path)
    data = cb.read_map(path)

    levels = cb.find_child(data, "levels")
    if levels is None:
        return "Invalid map."

    name = room_name if room_name.startswith("lvl_") else f"lvl_{room_name}"
    children = levels.get("__children", [])
    before = len(children)
    levels["__children"] = [
        r for r in children
        if r.get("name") != name and r.get("name") != room_name
    ]

    if len(levels["__children"]) == before:
        return f"Room '{room_name}' not found."

    cb.write_map(path, data)
    return f"Removed room '{room_name}'."


@mcp.tool()
def create_map(map_path: str, package_name: str = "") -> str:
    """Create a new empty Celeste .bin map file.

    Args:
        map_path: Path for the new file (relative to workspace)
        package_name: Map package name (e.g. "Maggy/PCG/MyMap")
    """
    path = _resolve(map_path)
    if path.exists():
        return f"File already exists: {map_path}"

    if not package_name:
        package_name = path.stem

    data: dict = {
        "__name": "Map",
        "_package": package_name,
        "__children": [
            {"__name": "Filler", "__children": []},
            {"__name": "levels", "__children": []},
            {
                "__name": "Style",
                "__children": [
                    {"__name": "Foregrounds", "__children": []},
                    {"__name": "Backgrounds", "__children": []},
                ],
            },
        ],
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    cb.write_map(path, data)
    return f"Created empty map: {map_path} (package: {package_name})"


@mcp.tool()
def generate_starter_map(
    map_path: str,
    template: str = "minimal",
    package_name: str = "",
    room_prefix: str = "",
    custom_rooms_json: str = "",
    auto_connect_adjacent: bool = True,
    overwrite: bool = False,
) -> str:
    """Generate a playable starter map from a built-in template.

    This is a high-level one-shot map scaffold tool designed for faster mod
    iteration. It builds rooms, solid tiles, and marker-based starter entities.

    Marker legend in templates:
      P = player spawn, R = strawberry, Q = refill, C = checkpoint

    Args:
        map_path: Output .bin map path (relative to workspace or absolute)
        template: Starter template: "minimal", "entity", or "route"
        package_name: Package name override (defaults to output filename stem)
        room_prefix: Optional prefix applied to generated room names
        custom_rooms_json: Optional JSON array of custom room specs. If set,
            template is ignored. Each room accepts: name, layout, optional x/y.
        auto_connect_adjacent: Auto-create two-way teleport triggers between
            rooms that share an edge.
        overwrite: Replace file if it already exists
    """
    template_key = template.strip().lower()
    path = _resolve(map_path)

    if path.exists() and not overwrite:
        return (
            f"File already exists: {map_path}. "
            "Set overwrite=True to replace it."
        )

    if not package_name:
        package_name = path.stem

    map_data: dict = {
        "__name": "Map",
        "_package": package_name,
        "__children": [
            {"__name": "Filler", "__children": []},
            {"__name": "levels", "__children": []},
            {
                "__name": "Style",
                "__children": [
                    {"__name": "Foregrounds", "__children": []},
                    {"__name": "Backgrounds", "__children": []},
                ],
            },
        ],
    }

    levels = cb.find_child(map_data, "levels")
    if levels is None:
        return "Internal error: failed to create map levels section."

    try:
        if custom_rooms_json.strip():
            specs, stylegrounds = _custom_room_specs(custom_rooms_json)
        else:
            specs = _starter_room_specs(template_key)
            stylegrounds = {"foregrounds": [], "backgrounds": []}
    except ValueError as exc:
        return str(exc)

    made_names: list[str] = []
    built_rooms: list[dict] = []
    for spec in specs:
        base_name = spec["name"]
        full_name = f"{room_prefix}{base_name}" if room_prefix else base_name
        room = _build_room_from_layout(
            room_name=full_name,
            x=spec["x"],
            y=spec["y"],
            layout=spec["layout"],
            spec=spec,
        )
        made_names.append(room.get("name", "?"))
        built_rooms.append(room)
        levels["__children"].append(room)

    link_count = 0
    if auto_connect_adjacent and len(built_rooms) > 1:
        link_count = _auto_connect_rooms_with_teleports(built_rooms)

    _apply_stylegrounds(map_data, stylegrounds)

    path.parent.mkdir(parents=True, exist_ok=True)
    cb.write_map(path, map_data)

    return (
        f"Generated starter map '{path.name}' with template '{template_key}'.\n"
        f"Package: {package_name}\n"
        f"Rooms ({len(made_names)}): {', '.join(made_names)}\n"
        f"Auto links: {link_count}\n"
        "Marker legend: P=player, R=strawberry, Q=refill, C=checkpoint"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTITY / TRIGGER CATALOG TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_entity_definitions(filter_text: str = "") -> str:
    """List available Lönn entity definitions from the project.

    Args:
        filter_text: Optional text to filter filenames
    """
    ent_dir = WORKSPACE / "Loenn" / "entities"
    if not ent_dir.exists():
        return "No Loenn/entities/ directory found."

    files = sorted(ent_dir.glob("*.lua"))
    if filter_text:
        fl = filter_text.lower()
        files = [f for f in files if fl in f.stem.lower()]

    if not files:
        return "No matching entity definitions."

    lines = [f"Entity definitions ({len(files)} files):"]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"\.name\s*=\s*[\"']([^\"']+)", text)
            label = m.group(1) if m else f.stem
        except Exception:
            label = f.stem
        lines.append(f"  {f.stem}  →  {label}")
    return "\n".join(lines)


@mcp.tool()
def get_entity_definition(entity_file: str) -> str:
    """Read a Lönn entity Lua definition and extract its properties.

    Args:
        entity_file: Filename (e.g. "kirbyBoss" or "kirbyBoss.lua")
    """
    if not entity_file.endswith(".lua"):
        entity_file += ".lua"

    ent_dir = (WORKSPACE / "Loenn" / "entities").resolve()
    path = (ent_dir / entity_file).resolve()
    # Guard against path traversal (e.g. entity_file = "../../secrets")
    try:
        path.relative_to(ent_dir)
    except ValueError:
        return "Invalid entity file path."
    if not path.exists():
        return f"Entity file not found: {entity_file}"

    text = path.read_text(encoding="utf-8", errors="replace")

    names = re.findall(r"\.name\s*=\s*[\"']([^\"']+)", text)
    placements = re.findall(
        r"placements.*?name\s*=\s*[\"']([^\"']+)", text, re.DOTALL
    )
    data_blocks = re.findall(r"data\s*=\s*\{([^}]+)\}", text)

    lines = [f"=== {entity_file} ==="]
    if names:
        lines.append(f"Names: {', '.join(names)}")
    if placements:
        lines.append(f"Placements: {', '.join(placements)}")
    if data_blocks:
        lines.append("\nDefault properties:")
        for block in data_blocks[:3]:
            for prop in re.findall(r"(\w+)\s*=\s*([^,\n]+)", block):
                lines.append(f"  {prop[0]} = {prop[1].strip()}")

    lines.append(f"\n--- Source ({len(text)} chars) ---")
    if len(text) > 4000:
        lines.append(text[:4000] + "\n... (truncated)")
    else:
        lines.append(text)

    return "\n".join(lines)


@mcp.tool()
def list_trigger_definitions(filter_text: str = "") -> str:
    """List available Lönn trigger definitions.

    Args:
        filter_text: Optional text to filter filenames
    """
    trig_dir = WORKSPACE / "Loenn" / "triggers"
    if not trig_dir.exists():
        return "No Loenn/triggers/ directory found."

    files = sorted(trig_dir.glob("*.lua"))
    if filter_text:
        fl = filter_text.lower()
        files = [f for f in files if fl in f.stem.lower()]

    lines = [f"Trigger definitions ({len(files)} files):"]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"\.name\s*=\s*[\"']([^\"']+)", text)
            label = m.group(1) if m else f.stem
        except Exception:
            label = f.stem
        lines.append(f"  {f.stem}  →  {label}")
    return "\n".join(lines)


@mcp.tool()
def list_effect_definitions(filter_text: str = "") -> str:
    """List available Lönn effect definitions.

    Args:
        filter_text: Optional text to filter filenames
    """
    fx_dir = WORKSPACE / "Loenn" / "effects"
    if not fx_dir.exists():
        return "No Loenn/effects/ directory found."

    files = sorted(fx_dir.glob("*.lua"))
    if filter_text:
        fl = filter_text.lower()
        files = [f for f in files if fl in f.stem.lower()]

    lines = [f"Effect definitions ({len(files)} files):"]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"\.name\s*=\s*[\"']([^\"']+)", text)
            label = m.group(1) if m else f.stem
        except Exception:
            label = f.stem
        lines.append(f"  {f.stem}  →  {label}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  ANALYSIS TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analyze_map(map_path: str) -> str:
    """Get detailed statistics about a map file.

    Args:
        map_path: Path to the .bin file
    """
    path = _resolve(map_path)
    if not path.exists():
        return f"File not found: {map_path}"

    data = cb.read_map(path)
    rooms = cb.get_rooms(data)

    total_ent = 0
    total_trig = 0
    total_fg_dec = 0
    total_bg_dec = 0
    entity_types: dict[str, int] = {}

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    for room in rooms:
        x, y = room.get("x", 0), room.get("y", 0)
        w, h = room.get("width", 0), room.get("height", 0)
        min_x, min_y = min(min_x, x), min(min_y, y)
        max_x, max_y = max(max_x, x + w), max(max_y, y + h)

        for section, label in [
            ("entities", "ent"),
            ("triggers", "trig"),
            ("fgdecals", "fgdec"),
            ("bgdecals", "bgdec"),
        ]:
            el = cb.find_child(room, section)
            if not el:
                continue
            children = el.get("__children", [])
            n = len(children)
            if label == "ent":
                total_ent += n
                for c in children:
                    t = c.get("__name", "unknown")
                    entity_types[t] = entity_types.get(t, 0) + 1
            elif label == "trig":
                total_trig += n
            elif label == "fgdec":
                total_fg_dec += n
            elif label == "bgdec":
                total_bg_dec += n

    lines = [
        f"Map: {data.get('_package', '?')}",
        f"File: {path.name} ({path.stat().st_size / 1024:.1f} KB)",
        "",
        f"Rooms: {len(rooms)}",
        f"Entities: {total_ent}",
        f"Triggers: {total_trig}",
        f"Decals: {total_fg_dec} fg + {total_bg_dec} bg",
    ]

    if rooms:
        lines += [
            "",
            f"Bounds: ({min_x},{min_y}) → ({max_x},{max_y})",
            f"Span: {max_x - min_x}x{max_y - min_y} px",
        ]

    if entity_types:
        top = sorted(entity_types.items(), key=lambda x: -x[1])
        lines.append(f"\nEntity types ({len(entity_types)} unique):")
        for name, count in top[:25]:
            lines.append(f"  {name}: {count}")
        if len(top) > 25:
            lines.append(f"  ... +{len(top) - 25} more")

    return "\n".join(lines)


@mcp.tool()
def visualize_map_layout(map_path: str) -> str:
    """Generate an ASCII visualization of all room positions in a map.

    Args:
        map_path: Path to the .bin file
    """
    path = _resolve(map_path)
    data = cb.read_map(path)
    rooms = cb.get_rooms(data)

    if not rooms:
        return "No rooms in this map."

    # Determine scale
    min_x = min(r.get("x", 0) for r in rooms)
    min_y = min(r.get("y", 0) for r in rooms)
    max_x = max(r.get("x", 0) + r.get("width", 0) for r in rooms)
    max_y = max(r.get("y", 0) + r.get("height", 0) for r in rooms)

    span_x = max_x - min_x or 1
    span_y = max_y - min_y or 1
    scale = max(span_x // 100, span_y // 50, 32)

    grid_w = span_x // scale + 2
    grid_h = span_y // scale + 2
    grid = [[" "] * grid_w for _ in range(grid_h)]

    for i, room in enumerate(rooms):
        rx = (room.get("x", 0) - min_x) // scale
        ry = (room.get("y", 0) - min_y) // scale
        rw = max(1, room.get("width", 0) // scale)
        rh = max(1, room.get("height", 0) // scale)
        ch = chr(ord("A") + i % 26) if i < 26 else str(i % 10)

        for dy in range(rh):
            for dx in range(rw):
                gx, gy = rx + dx, ry + dy
                if 0 <= gx < grid_w and 0 <= gy < grid_h:
                    if dy == 0 or dy == rh - 1 or dx == 0 or dx == rw - 1:
                        grid[gy][gx] = ch
                    else:
                        grid[gy][gx] = "·"

    lines = ["".join(row).rstrip() for row in grid]
    while lines and not lines[-1].strip():
        lines.pop()

    legend = ["\nLegend:"]
    for i, room in enumerate(rooms):
        ch = chr(ord("A") + i % 26) if i < 26 else str(i % 10)
        legend.append(f"  {ch} = {room.get('name', '?')}")

    return "\n".join(lines + legend)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAP PREVIEW TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def preview_map_section(
    map_path: str,
    prefix: str = "",
    center_room: str = "",
    cols: int = 140,
    rows: int = 60,
) -> str:
    """Generate an ASCII preview of a map section, like a Lönn mini-map.

    Shows room boxes with names, borders drawn with box-drawing characters,
    checkpoint markers, and entity counts. Zoom into a specific area by
    providing a room prefix (e.g. "g-") or a center room name.

    Args:
        map_path: Path to the .bin file
        prefix: Only show rooms whose name starts with this (e.g. "g-", "h-")
        center_room: Center the view on this room name
        cols: Terminal width for the preview (default 140)
        rows: Terminal height for the preview (default 60)
    """
    path = _resolve(map_path)
    data = cb.read_map(path)
    all_rooms = cb.get_rooms(data)

    if not all_rooms:
        return "No rooms in this map."

    # Filter rooms
    if prefix:
        pfx = prefix if prefix.startswith("lvl_") else f"lvl_{prefix}"
        rooms = [r for r in all_rooms if r.get("name", "").startswith(pfx)]
        if not rooms:
            return f"No rooms matching prefix '{prefix}'."
    else:
        rooms = all_rooms

    # Determine viewport bounds
    if center_room:
        cn = center_room if center_room.startswith("lvl_") else f"lvl_{center_room}"
        cr = next((r for r in all_rooms if r.get("name") == cn), None)
        if cr:
            cx = cr["x"] + cr["width"] // 2
            cy = cr["y"] + cr["height"] // 2
        else:
            cx = sum(r["x"] + r["width"] // 2 for r in rooms) // len(rooms)
            cy = sum(r["y"] + r["height"] // 2 for r in rooms) // len(rooms)
    else:
        min_x = min(r.get("x", 0) for r in rooms)
        min_y = min(r.get("y", 0) for r in rooms)
        max_x = max(r.get("x", 0) + r.get("width", 0) for r in rooms)
        max_y = max(r.get("y", 0) + r.get("height", 0) for r in rooms)
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2

    # Calculate scale so filtered rooms fit in the grid
    min_x = min(r.get("x", 0) for r in rooms)
    min_y = min(r.get("y", 0) for r in rooms)
    max_x = max(r.get("x", 0) + r.get("width", 0) for r in rooms)
    max_y = max(r.get("y", 0) + r.get("height", 0) for r in rooms)
    span_x = max_x - min_x or 1
    span_y = max_y - min_y or 1

    # Pick scale to fit in grid, leave margin
    usable_cols = cols - 2
    usable_rows = rows - 2
    scale_x = max(span_x // usable_cols, 1)
    scale_y = max(span_y // usable_rows, 1)
    scale = max(scale_x, scale_y * 2)  # chars are ~2x taller than wide

    grid_w = span_x // scale + 4
    grid_h = span_y // (scale * 2) + 4  # double because chars are tall
    grid_w = min(grid_w, cols)
    grid_h = min(grid_h, rows)

    # Initialize grid
    grid = [[" "] * grid_w for _ in range(grid_h)]

    # Draw rooms
    room_info = []
    for room in rooms:
        rx = room.get("x", 0)
        ry = room.get("y", 0)
        rw = room.get("width", 0)
        rh = room.get("height", 0)
        name = room.get("name", "?").replace("lvl_", "")

        # Grid coordinates
        gx = (rx - min_x) // scale
        gy = (ry - min_y) // (scale * 2)
        gw = max(2, rw // scale)
        gh = max(2, rh // (scale * 2))

        # Count entities
        ent_count = 0
        has_checkpoint = False
        has_player = False
        for child in room.get("__children", []):
            if child.get("__name") == "entities":
                for ent in child.get("__children", []):
                    ent_count += 1
                    if ent.get("__name") == "checkpoint":
                        has_checkpoint = True
                    if ent.get("__name") == "player":
                        has_player = True

        # Draw box
        for dy in range(gh):
            for dx in range(gw):
                x, y = gx + dx, gy + dy
                if 0 <= x < grid_w and 0 <= y < grid_h:
                    if dy == 0 and dx == 0:
                        grid[y][x] = "┌"
                    elif dy == 0 and dx == gw - 1:
                        grid[y][x] = "┐"
                    elif dy == gh - 1 and dx == 0:
                        grid[y][x] = "└"
                    elif dy == gh - 1 and dx == gw - 1:
                        grid[y][x] = "┘"
                    elif dy == 0 or dy == gh - 1:
                        grid[y][x] = "─"
                    elif dx == 0 or dx == gw - 1:
                        grid[y][x] = "│"
                    else:
                        grid[y][x] = "·"

        # Write room name inside the box
        label = name
        if has_checkpoint:
            label = "★" + name
        lx = gx + 1
        ly = gy + 1 if gh > 2 else gy
        for ci, ch in enumerate(label[:gw - 2]):
            x = lx + ci
            if 0 <= x < grid_w and 0 <= ly < grid_h:
                grid[ly][x] = ch

        # Write entity count on line below name if space
        if gh > 3:
            count_str = f"{ent_count}e"
            ly2 = gy + 2
            for ci, ch in enumerate(count_str[:gw - 2]):
                x = lx + ci
                if 0 <= x < grid_w and 0 <= ly2 < grid_h:
                    grid[ly2][x] = ch

        room_info.append((name, rx, ry, rw, rh, ent_count, has_checkpoint))

    # Render grid
    output_lines = ["".join(row).rstrip() for row in grid]
    while output_lines and not output_lines[-1].strip():
        output_lines.pop()

    # Add summary below
    output_lines.append("")
    output_lines.append(f"Rooms shown: {len(rooms)}  |  Scale: 1 char ≈ {scale}px wide, {scale*2}px tall")
    output_lines.append("")

    # Room table
    output_lines.append(f"{'Room':<14} {'Pos':>16} {'Size':>10} {'Ents':>5} {'CP':>3}")
    output_lines.append("─" * 52)
    for name, rx, ry, rw, rh, ec, cp in room_info:
        cp_mark = "★" if cp else ""
        output_lines.append(f"{name:<14} ({rx:>6},{ry:>6}) {rw:>4}x{rh:<4} {ec:>5} {cp_mark:>3}")

    return "\n".join(output_lines)


@mcp.tool()
def render_map_html(
    map_path: str,
    prefix: str = "",
    output_file: str = "",
) -> str:
    """Render an interactive HTML map preview with zoom, pan, search, and detail panel.

    Features: zoom/pan (wheel, drag, pinch), hover tooltips, click-to-select room
    detail panel (entity/trigger breakdown), live search filter, minimap with
    viewport indicator, toggleable grid and labels, keyboard shortcuts.

    Args:
        map_path: Path to the .bin file
        prefix: Only show rooms matching this prefix (e.g. "g-", "w-")
        output_file: Output HTML filename (default: map_preview.html in Temp/)
    """
    import json as _json

    path = _resolve(map_path)
    data = cb.read_map(path)
    all_rooms = cb.get_rooms(data)

    if not all_rooms:
        return "No rooms in this map."

    if prefix:
        pfx = prefix if prefix.startswith("lvl_") else f"lvl_{prefix}"
        rooms = [r for r in all_rooms if r.get("name", "").startswith(pfx)]
        if not rooms:
            return f"No rooms matching prefix '{prefix}'."
    else:
        rooms = all_rooms

    # World bounds
    min_x = min(r.get("x", 0) for r in rooms)
    min_y = min(r.get("y", 0) for r in rooms)
    max_x = max(r.get("x", 0) + r.get("width", 0) for r in rooms)
    max_y = max(r.get("y", 0) + r.get("height", 0) for r in rooms)
    margin = 320
    vw = max_x - min_x + margin * 2
    vh = max_y - min_y + margin * 2

    PALETTE = [
        "#4a80c8", "#5aa050", "#c86040", "#8040c0",
        "#40a8b0", "#c09030", "#b83880", "#3890c0",
        "#70b030", "#c04040",
    ]

    rooms_data = []
    svg_groups = []

    for i, room in enumerate(rooms):
        rx = room.get("x", 0) - min_x + margin
        ry = room.get("y", 0) - min_y + margin
        rw = room.get("width", 0)
        rh = room.get("height", 0)
        name = room.get("name", "?").replace("lvl_", "")

        area = name.split("-")[0] if "-" in name else name
        color = PALETTE[abs(hash(area)) % len(PALETTE)]

        has_cp = False
        has_strawberry = False
        has_heart = False
        has_cassette = False
        entity_types: dict = {}
        trigger_types: dict = {}

        for child in room.get("__children", []):
            cname = child.get("__name")
            if cname == "entities":
                for ent in child.get("__children", []):
                    etype = ent.get("__name", "?")
                    entity_types[etype] = entity_types.get(etype, 0) + 1
                    if etype == "checkpoint": has_cp = True
                    if etype in ("strawberry", "goldenBerry", "memorialTextController"):
                        has_strawberry = True
                    if etype in ("blackGem", "heartGem", "darkChest"):
                        has_heart = True
                    if etype == "cassette":
                        has_cassette = True
            elif cname == "triggers":
                for t in child.get("__children", []):
                    ttype = t.get("__name", "?")
                    trigger_types[ttype] = trigger_types.get(ttype, 0) + 1

        ent_count = sum(entity_types.values())
        trigger_count = sum(trigger_types.values())
        top_ents = sorted(entity_types.items(), key=lambda x: -x[1])[:14]
        top_trigs = sorted(trigger_types.items(), key=lambda x: -x[1])[:8]

        badges = []
        if has_cp: badges.append("★")
        if has_strawberry: badges.append("🍓")
        if has_heart: badges.append("💎")
        if has_cassette: badges.append("📼")

        rooms_data.append({
            "idx": i, "name": name,
            "wx": room.get("x", 0), "wy": room.get("y", 0),
            "w": rw, "h": rh,
            "sx": rx, "sy": ry,
            "color": color,
            "has_cp": has_cp,
            "badges": badges,
            "ent": ent_count, "trig": trigger_count,
            "entities": top_ents,
            "triggers": top_trigs,
        })

        fs = max(10, min(20, rw // max(len(name), 1)))
        cx = rx + rw / 2
        cy = ry + rh / 2
        stroke = "#ffd700" if has_cp else "#5a5a7a"
        stroke_w = 3 if has_cp else 1.5
        badge_str = " ".join(badges)
        disp_label = (badge_str + " " if badge_str else "") + name
        sub_label = f"{ent_count}e · {trigger_count}t · {rw}×{rh}"

        g_parts = [
            f'<rect class="rb" x="{rx}" y="{ry}" width="{rw}" height="{rh}" '
            f'fill="{color}" fill-opacity="0.72" stroke="{stroke}" stroke-width="{stroke_w}" rx="4"/>',
            f'<rect class="rh" x="{rx}" y="{ry}" width="{rw}" height="{rh}" '
            f'fill="none" stroke="transparent" rx="4" pointer-events="none"/>',
            f'<text class="ln" x="{cx:.1f}" y="{cy + fs*0.35:.1f}" '
            f'text-anchor="middle" font-size="{fs}" fill="white" '
            f'font-family="monospace" font-weight="bold" filter="url(#shadow)">{disp_label}</text>',
            f'<text class="ls" x="{cx:.1f}" y="{cy + fs + max(8, fs-4):.1f}" '
            f'text-anchor="middle" font-size="{max(8, fs-4)}" fill="#aab" '
            f'font-family="monospace" filter="url(#shadow)">{sub_label}</text>',
            f'<rect class="ri" x="{rx}" y="{ry}" width="{rw}" height="{rh}" '
            f'fill="transparent" data-idx="{i}"/>',
        ]
        svg_groups.append(f'<g class="rg" id="rg{i}">' + "".join(g_parts) + "</g>")

    svg_body = "\n".join(svg_groups)
    rooms_json = _json.dumps(rooms_data)

    # Grid lines every 320px (one standard Celeste room width)
    grid_parts = []
    for y in range(0, vh + 320, 320):
        grid_parts.append(f'<line x1="0" y1="{y}" x2="{vw}" y2="{y}"/>')
    for x in range(0, vw + 320, 320):
        grid_parts.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{vh}"/>')
    grid_svg = "\n    ".join(grid_parts)

    # ── CSS (plain string — no f-string brace conflicts) ──────────────────────
    css = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #12121e; color: #d8d8e8;
  font-family: Consolas, 'Courier New', monospace;
  display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
#topbar { display: flex; align-items: center; gap: 10px; padding: 7px 14px;
  background: #1c1c30; border-bottom: 1px solid #2e2e48; flex-shrink: 0; }
#title { font-size: 14px; font-weight: bold; color: #9ab0ff; flex: 1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#stats { font-size: 11px; color: #556; white-space: nowrap; }
#toolbar { display: flex; align-items: center; gap: 5px; padding: 5px 12px;
  background: #161626; border-bottom: 1px solid #252538;
  flex-shrink: 0; flex-wrap: wrap; }
.btn { background: #222238; color: #bbc; border: 1px solid #3a3a56; padding: 3px 9px;
  border-radius: 4px; cursor: pointer; font-size: 12px; font-family: inherit;
  white-space: nowrap; line-height: 20px; }
.btn:hover { background: #2e2e50; }
.btn.on { background: #2c2c56; border-color: #5060a0; color: #cce; }
#zdsp { font-size: 12px; color: #667; min-width: 46px; text-align: center; }
#search { background: #222238; color: #ccd; border: 1px solid #3a3a56;
  padding: 3px 8px; border-radius: 4px; font-size: 12px;
  font-family: inherit; width: 165px; }
#search:focus { outline: none; border-color: #6878c8; }
#search::placeholder { color: #445; }
.sep { width: 1px; height: 18px; background: #252538; margin: 0 2px; }
#main { display: flex; flex: 1; overflow: hidden; }
#wrap { flex: 1; overflow: hidden; cursor: grab; position: relative; background: #12121e; }
#wrap.dragging { cursor: grabbing; }
svg { display: block; }
/* label zoom tiers */
svg.z0 .ln, svg.z0 .ls { display: none; }
svg.z1 .ls { display: none; }
/* room appearance */
.rh { transition: stroke 0.07s; }
.rg:hover .rh { stroke: rgba(255,255,255,0.9) !important; stroke-width: 3 !important; }
.rg.sel .rh { stroke: white !important; stroke-width: 4 !important; }
.rg.dim { opacity: 0.1; }
.ri { cursor: pointer; }
/* sidebar */
#sb { width: 252px; flex-shrink: 0; background: #181828;
  border-left: 1px solid #252538; display: flex; flex-direction: column; }
#sb.closed { display: none; }
#sb-hdr { padding: 10px 12px 8px; background: #1e1e34; border-bottom: 1px solid #252538; }
#sb-idx { font-size: 10px; color: #446; text-transform: uppercase; letter-spacing: 1px; }
#sb-name { font-size: 18px; color: #e0e8ff; font-weight: bold; margin: 2px 0; }
#sb-meta { font-size: 11px; color: #667; }
#sb-badges { font-size: 16px; margin-top: 5px; letter-spacing: 3px; min-height: 22px; }
#sb-body { flex: 1; overflow-y: auto; padding: 8px 12px; font-size: 12px; }
#sb-body::-webkit-scrollbar { width: 5px; }
#sb-body::-webkit-scrollbar-track { background: #181828; }
#sb-body::-webkit-scrollbar-thumb { background: #333350; border-radius: 3px; }
.sec { font-size: 10px; color: #4858a0; text-transform: uppercase; letter-spacing: 1.5px;
  border-bottom: 1px solid #222238; padding-bottom: 3px; margin: 10px 0 5px; }
.none { color: #334; font-size: 11px; padding: 2px 0; }
.erow { display: flex; justify-content: space-between; padding: 2px 0; }
.en { color: #9aaabb; flex: 1; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; font-size: 11px; }
.ec { color: #5868b0; font-size: 11px; min-width: 28px; text-align: right; }
#sb-copy { padding: 6px; margin: 6px 10px 10px; background: #1e1e34;
  border: 1px solid #303050; border-radius: 5px; cursor: pointer;
  font-size: 11px; color: #8898b8; text-align: center; font-family: inherit; width: calc(100% - 20px); }
#sb-copy:hover { background: #252545; color: #aab8d0; }
#sb-empty { flex: 1; display: flex; align-items: center; justify-content: center;
  color: #334; font-size: 12px; text-align: center; line-height: 2; }
/* tooltip */
#tip { position: fixed; background: #1c1c30; border: 1px solid #3a3a58;
  border-radius: 6px; padding: 8px 10px; font-size: 11px;
  pointer-events: none; z-index: 200; opacity: 0; transition: opacity 0.07s;
  box-shadow: 0 4px 18px rgba(0,0,0,0.65); max-width: 260px; white-space: pre-line; }
#tip.vis { opacity: 1; }
#tip-name { font-size: 13px; font-weight: bold; color: #b0c0ff; margin-bottom: 3px; }
#tip-size { color: #667; margin-bottom: 3px; }
#tip-ents { color: #8899aa; }
/* minimap */
#mm-wrap { position: absolute; bottom: 12px; right: 12px; border: 1px solid #2a2a44;
  border-radius: 5px; overflow: hidden; cursor: pointer;
  box-shadow: 0 2px 12px rgba(0,0,0,0.6); }
#mmv { position: absolute; top: 0; left: 0; pointer-events: none; }
"""

    # ── JS (plain string so literal {} needs no escaping) ─────────────────────
    js = r"""
(function() {
const wrap = document.getElementById('wrap');
const svg  = document.getElementById('svg');
const zdsp = document.getElementById('zdsp');
const tip  = document.getElementById('tip');
const sb   = document.getElementById('sb');
const ZOOM_STEP = 1.25, MIN_Z = 0.04, MAX_Z = 12;
let zoom = 1, panX = 0, panY = 0;
let dragging = false, dragMoved = false, lx = 0, ly = 0;
let selIdx = -1;

// ── zoom / pan ────────────────────────────────────────────────────────────
function fitToWindow() {
  const ww = wrap.clientWidth, wh = wrap.clientHeight;
  zoom = Math.min(ww / SVG_W, wh / SVG_H) * 0.93;
  panX = (ww - SVG_W * zoom) / 2;
  panY = (wh - SVG_H * zoom) / 2;
}
function clamp() {
  const ww = wrap.clientWidth, wh = wrap.clientHeight, pad = 120;
  panX = Math.min(panX, pad);
  panY = Math.min(panY, pad);
  panX = Math.max(panX, ww - SVG_W * zoom - pad);
  panY = Math.max(panY, wh - SVG_H * zoom - pad);
}
function apply() {
  svg.style.transform = `translate(${panX}px,${panY}px) scale(${zoom})`;
  svg.style.transformOrigin = '0 0';
  zdsp.textContent = Math.round(zoom * 100) + '%';
  svg.className = zoom < 0.15 ? 'z0' : zoom < 0.4 ? 'z1' : 'z2';
  drawMMViewport();
}
function zoomAt(cx, cy, f) {
  const nz = Math.min(MAX_Z, Math.max(MIN_Z, zoom * f));
  const s = nz / zoom;
  panX = cx - s * (cx - panX);
  panY = cy - s * (cy - panY);
  zoom = nz; clamp(); apply();
}
fitToWindow(); apply();

// ── mouse wheel ───────────────────────────────────────────────────────────
wrap.addEventListener('wheel', e => {
  e.preventDefault();
  const r = wrap.getBoundingClientRect();
  zoomAt(e.clientX - r.left, e.clientY - r.top,
         e.deltaY < 0 ? ZOOM_STEP : 1/ZOOM_STEP);
}, {passive: false});

// ── drag to pan ───────────────────────────────────────────────────────────
// dragMoved is only true once the pointer has moved > 8px, preventing
// accidental click suppression from normal hand tremor.
wrap.addEventListener('mousedown', e => {
  if (e.button !== 0) return;
  dragging = true; dragMoved = false; lx = e.clientX; ly = e.clientY;
  wrap.classList.add('dragging');
});
window.addEventListener('mousemove', e => {
  if (!dragging) return;
  const dx = e.clientX - lx, dy = e.clientY - ly;
  if (!dragMoved && Math.abs(dx) < 8 && Math.abs(dy) < 8) return; // ignore tremor
  dragMoved = true;
  panX += dx; panY += dy; lx = e.clientX; ly = e.clientY;
  clamp(); apply();
});
window.addEventListener('mouseup', () => {
  dragging = false; wrap.classList.remove('dragging');
});

// ── touch pinch/pan ───────────────────────────────────────────────────────
let touches = {}, lastDist = null;
wrap.addEventListener('touchstart', e => {
  for (const t of e.changedTouches) touches[t.identifier] = {x: t.clientX, y: t.clientY};
}, {passive: true});
wrap.addEventListener('touchmove', e => {
  e.preventDefault();
  if (e.touches.length === 1) {
    const t = e.touches[0], p = touches[t.identifier] || {x: t.clientX, y: t.clientY};
    panX += t.clientX - p.x; panY += t.clientY - p.y;
    touches[t.identifier] = {x: t.clientX, y: t.clientY};
    clamp(); apply();
  } else if (e.touches.length === 2) {
    const [a, b] = e.touches;
    const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    if (lastDist !== null) {
      const r = wrap.getBoundingClientRect();
      zoomAt((a.clientX + b.clientX)/2 - r.left,
             (a.clientY + b.clientY)/2 - r.top, d/lastDist);
    }
    lastDist = d;
    for (const t of e.touches) touches[t.identifier] = {x: t.clientX, y: t.clientY};
  }
}, {passive: false});
wrap.addEventListener('touchend', e => {
  for (const t of e.changedTouches) delete touches[t.identifier];
  if (e.touches.length < 2) lastDist = null;
}, {passive: true});

// ── keyboard shortcuts ────────────────────────────────────────────────────
window.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key === '=' || e.key === '+') zoomAt(wrap.clientWidth/2, wrap.clientHeight/2, ZOOM_STEP);
  else if (e.key === '-')             zoomAt(wrap.clientWidth/2, wrap.clientHeight/2, 1/ZOOM_STEP);
  else if (e.key === '0') { fitToWindow(); apply(); }
  else if (e.key === 'Escape') { selectRoom(-1); }
  else if (e.key === 'f' || e.key === 'F') { document.getElementById('search').focus(); }
});

// ── tooltip ───────────────────────────────────────────────────────────────
const tipName = document.getElementById('tip-name');
const tipSize = document.getElementById('tip-size');
const tipEnts = document.getElementById('tip-ents');

wrap.addEventListener('mousemove', e => {
  let tx = e.clientX + 16, ty = e.clientY - 8;
  if (tx + 270 > window.innerWidth) tx = e.clientX - 260;
  tip.style.left = tx + 'px';
  tip.style.top  = ty + 'px';
});

const roomsEl = document.getElementById('rooms');
roomsEl.addEventListener('mouseover', e => {
  const idx = e.target.dataset?.idx;
  if (idx === undefined) { tip.classList.remove('vis'); return; }
  const r = ROOMS[+idx];
  tipName.textContent = ([...r.badges, r.name]).join(' ');
  tipSize.textContent = r.w + ' × ' + r.h + ' px  (world ' + r.wx + ', ' + r.wy + ')';
  const top3 = r.entities.slice(0, 3).map(([n, c]) => n + ': ' + c).join('  ·  ');
  tipEnts.textContent = r.ent + ' entities · ' + r.trig + ' triggers' +
                        (top3 ? '\n' + top3 : '');
  tip.classList.add('vis');
});
roomsEl.addEventListener('mouseout', e => {
  if (e.target.dataset?.idx !== undefined) tip.classList.remove('vis');
});

// ── room click / select ───────────────────────────────────────────────────
roomsEl.addEventListener('click', e => {
  if (dragMoved) return;
  const idx = e.target.dataset?.idx;
  if (idx === undefined) return;
  selectRoom(+idx === selIdx ? -1 : +idx);
});

function getRG(i) { return document.getElementById('rg' + i); }

function selectRoom(idx) {
  if (selIdx >= 0) getRG(selIdx)?.classList.remove('sel');
  selIdx = idx;
  if (idx >= 0) {
    getRG(idx)?.classList.add('sel');
    showSidebar(ROOMS[idx]);
  } else {
    hideSidebar();
  }
}

// ── sidebar ───────────────────────────────────────────────────────────────
function showSidebar(r) {
  document.getElementById('sb-empty').style.display = 'none';
  document.getElementById('sb-hdr').style.display   = '';
  document.getElementById('sb-body').style.display  = '';
  document.getElementById('sb-copy').style.display  = '';
  document.getElementById('sb-idx').textContent  = 'Room ' + (r.idx + 1);
  document.getElementById('sb-name').textContent = r.name;
  document.getElementById('sb-meta').textContent =
      r.w + ' × ' + r.h + ' px  ·  (' + r.wx + ', ' + r.wy + ')';
  document.getElementById('sb-badges').textContent = r.badges.join('  ');

  let html = '<div class="sec">Entities (' + r.ent + ')</div>';
  if (!r.entities.length) html += '<div class="none">—</div>';
  for (const [n, c] of r.entities)
    html += '<div class="erow"><span class="en" title="' + n + '">' + n +
            '</span><span class="ec">' + c + '</span></div>';

  html += '<div class="sec">Triggers (' + r.trig + ')</div>';
  if (!r.triggers.length) html += '<div class="none">—</div>';
  for (const [n, c] of r.triggers)
    html += '<div class="erow"><span class="en" title="' + n + '">' + n +
            '</span><span class="ec">' + c + '</span></div>';

  document.getElementById('sb-body').innerHTML = html;
}

function hideSidebar() {
  document.getElementById('sb-empty').style.display  = '';
  document.getElementById('sb-hdr').style.display    = 'none';
  document.getElementById('sb-body').style.display   = 'none';
  document.getElementById('sb-copy').style.display   = 'none';
}

document.getElementById('sb-copy').addEventListener('click', () => {
  if (selIdx < 0) return;
  navigator.clipboard?.writeText(ROOMS[selIdx].name);
  const btn = document.getElementById('sb-copy');
  btn.textContent = '✓ Copied!';
  setTimeout(() => { btn.textContent = '📋 Copy name'; }, 1500);
});

// ── search / filter ───────────────────────────────────────────────────────
document.getElementById('search').addEventListener('input', e => {
  const q = e.target.value.trim().toLowerCase();
  ROOMS.forEach(r => {
    const g = getRG(r.idx);
    if (g) g.classList.toggle('dim', !!q && !r.name.toLowerCase().includes(q));
  });
});

// ── toolbar buttons ───────────────────────────────────────────────────────
document.getElementById('btn-zi').addEventListener('click', () =>
  zoomAt(wrap.clientWidth/2, wrap.clientHeight/2, ZOOM_STEP));
document.getElementById('btn-zo').addEventListener('click', () =>
  zoomAt(wrap.clientWidth/2, wrap.clientHeight/2, 1/ZOOM_STEP));
document.getElementById('btn-fit').addEventListener('click', () => { fitToWindow(); apply(); });

document.getElementById('btn-grid').addEventListener('click', function() {
  this.classList.toggle('on');
  document.getElementById('grid').style.display = this.classList.contains('on') ? '' : 'none';
});
document.getElementById('btn-lbl').addEventListener('click', function() {
  this.classList.toggle('on');
  const v = this.classList.contains('on') ? '' : 'none';
  document.querySelectorAll('.ln,.ls').forEach(el => el.style.display = v);
});

let sbOpen = true;
document.getElementById('btn-sb').addEventListener('click', function() {
  sbOpen = !sbOpen;
  this.classList.toggle('on', sbOpen);
  sb.classList.toggle('closed', !sbOpen);
});

// ── minimap ───────────────────────────────────────────────────────────────
const mmC   = document.getElementById('mm');
const mmCtx = mmC.getContext('2d');
const mmV   = document.getElementById('mmv');
const mmVCtx = mmV.getContext('2d');
const MM_W = mmC.width, MM_H = mmC.height;
const mmSX = MM_W / SVG_W, mmSY = MM_H / SVG_H;

// Draw static room tiles once
mmCtx.fillStyle = '#0e0e1a';
mmCtx.fillRect(0, 0, MM_W, MM_H);
for (const r of ROOMS) {
  mmCtx.fillStyle = r.color + 'bb';
  mmCtx.fillRect(r.sx * mmSX, r.sy * mmSY, Math.max(1, r.w * mmSX), Math.max(1, r.h * mmSY));
  if (r.has_cp) {
    mmCtx.strokeStyle = '#ffd700';
    mmCtx.lineWidth = 0.5;
    mmCtx.strokeRect(r.sx * mmSX, r.sy * mmSY, Math.max(1, r.w * mmSX), Math.max(1, r.h * mmSY));
  }
}

function drawMMViewport() {
  mmVCtx.clearRect(0, 0, MM_W, MM_H);
  const ww = wrap.clientWidth, wh = wrap.clientHeight;
  const vx = (-panX / zoom) * mmSX;
  const vy = (-panY / zoom) * mmSY;
  const vw2 = (ww / zoom) * mmSX;
  const vh2 = (wh / zoom) * mmSY;
  const cx = Math.max(0, vx), cy = Math.max(0, vy);
  const cw = Math.min(vw2, MM_W - Math.max(0, vx));
  const ch = Math.min(vh2, MM_H - Math.max(0, vy));
  if (cw > 0 && ch > 0) {
    mmVCtx.fillStyle = 'rgba(255,255,255,0.07)';
    mmVCtx.fillRect(cx, cy, cw, ch);
    mmVCtx.strokeStyle = 'rgba(255,255,255,0.75)';
    mmVCtx.lineWidth = 1.5;
    mmVCtx.strokeRect(cx, cy, cw, ch);
  }
}

// Click minimap to pan
mmC.addEventListener('click', e => {
  const r2 = mmC.getBoundingClientRect();
  const mx = (e.clientX - r2.left) / mmSX;
  const my = (e.clientY - r2.top) / mmSY;
  panX = wrap.clientWidth  / 2 - mx * zoom;
  panY = wrap.clientHeight / 2 - my * zoom;
  clamp(); apply();
});

drawMMViewport();
})();
"""

    # Prepend data constants (f-string only for the variable values)
    js_with_data = (
        f"const ROOMS = {rooms_json};\nconst SVG_W = {vw}, SVG_H = {vh};\n" + js
    )

    # ── Assemble HTML ─────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><title>Map Preview — {path.stem}</title>
<style>{css}</style>
</head><body>
<div id="topbar">
  <div id="title">🗺️ {path.stem}</div>
  <div id="stats">{len(rooms)} rooms · {prefix or 'all'} · scroll=zoom · drag=pan · click=details · F=search</div>
</div>
<div id="toolbar">
  <button class="btn" id="btn-zi" title="Zoom in (+)">＋</button>
  <span id="zdsp">100%</span>
  <button class="btn" id="btn-zo" title="Zoom out (-)">－</button>
  <button class="btn" id="btn-fit" title="Fit to window (0)">⟳ Fit</button>
  <div class="sep"></div>
  <button class="btn on" id="btn-grid">Grid</button>
  <button class="btn on" id="btn-lbl">Labels</button>
  <div class="sep"></div>
  <input id="search" type="text" placeholder="Search rooms… (F)">
  <div class="sep"></div>
  <button class="btn on" id="btn-sb" title="Toggle detail panel">Panel</button>
</div>
<div id="main">
  <div id="wrap">
    <svg id="svg" width="{vw}" height="{vh}" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <filter id="shadow">
          <feDropShadow dx="1" dy="1" stdDeviation="1.2"
            flood-color="#000" flood-opacity="0.9"/>
        </filter>
      </defs>
      <rect width="100%" height="100%" fill="#12121e"/>
      <g id="grid" stroke="#1e1e2c" stroke-width="1.5">
        {grid_svg}
      </g>
      <g id="rooms">{svg_body}</g>
    </svg>
    <div id="mm-wrap">
      <canvas id="mm"  width="180" height="110"></canvas>
      <canvas id="mmv" width="180" height="110"></canvas>
    </div>
  </div>
  <div id="sb">
    <div id="sb-empty">← Click a room<br>to view details</div>
    <div id="sb-hdr" style="display:none">
      <div id="sb-idx"></div>
      <div id="sb-name"></div>
      <div id="sb-meta"></div>
      <div id="sb-badges"></div>
    </div>
    <div id="sb-body" style="display:none"></div>
    <button id="sb-copy" style="display:none">📋 Copy name</button>
  </div>
</div>
<div id="tip">
  <div id="tip-name"></div>
  <div id="tip-size"></div>
  <div id="tip-ents"></div>
</div>
<script>{js_with_data}</script>
</body></html>"""

    # Write file
    if not output_file:
        out_dir = WORKSPACE / "Temp"
        out_dir.mkdir(exist_ok=True)
        output_file = str(out_dir / f"map_preview_{path.stem}.html")
    else:
        output_file = str(_resolve(output_file))

    Path(output_file).write_text(html, encoding="utf-8")
    return f"Preview saved to: {output_file}\nOpen this file in a browser to see the map.\nRooms shown: {len(rooms)}"




# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    mcp.run()


if __name__ == "__main__":
    main()
