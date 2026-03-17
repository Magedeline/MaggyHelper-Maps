#!/usr/bin/env python3
"""Build custom room JSON from a weighted archetype pool with basic playability checks."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

DEFAULT_HAZARD_CHARS = "Xx^*~!"


@dataclass(frozen=True)
class Archetype:
    archetype_id: str
    layout: str
    difficulty: int
    tags: List[str]
    weight: float
    open_left: bool
    open_right: bool
    hazard_chars: str


@dataclass(frozen=True)
class SequenceRules:
    required_tags: Set[str]
    min_tag_counts: Dict[str, int]
    excluded_adjacent_tag_pairs: Set[Tuple[str, str]]
    late_game_tags: Set[str]
    late_game_start_ratio: float


STYLEGROUND_PROFILES: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
    "normal": {
        "backgrounds": [
            {
                "name": "parallax",
                "texture": "bgs/02/bg0",
                "blendMode": "alphablend",
                "loopX": True,
                "loopY": True,
                "scrollX": 0.1,
                "scrollY": 0.05,
                "x": 0,
                "y": 0,
                "color": "ffffff",
                "alpha": 1.0,
                "flipX": False,
                "flipY": False,
                "instantIn": False,
                "instantOut": False,
            }
        ],
        "foregrounds": [],
    },
    "summit": {
        "backgrounds": [
            {
                "name": "parallax",
                "texture": "bgs/07/bg0",
                "blendMode": "alphablend",
                "loopX": True,
                "loopY": True,
                "scrollX": 0.2,
                "scrollY": 0.1,
                "x": 0,
                "y": 0,
                "color": "ffffff",
                "alpha": 1.0,
                "flipX": False,
                "flipY": False,
                "instantIn": False,
                "instantOut": False,
            }
        ],
        "foregrounds": [],
    },
    "wind": {
        "backgrounds": [
            {
                "name": "parallax",
                "texture": "bgs/04/bg0",
                "blendMode": "alphablend",
                "loopX": True,
                "loopY": True,
                "scrollX": 0.25,
                "scrollY": 0.05,
                "x": 0,
                "y": 0,
                "color": "ffffff",
                "alpha": 1.0,
                "flipX": False,
                "flipY": False,
                "instantIn": False,
                "instantOut": False,
            }
        ],
        "foregrounds": [{"name": "Wind"}],
    },
}


DECAL_PROFILES: Dict[str, Dict[str, List[str]]] = {
    "normal": {
        "fg": ["maggy/generic/grass_a", "maggy/generic/hanginggrass_a"],
        "bg": ["maggy/9_beyond_summit/cloud_a", "maggy/9_beyond_summit/cloud_b"],
    },
    "summit": {
        "fg": ["maggy/9_beyond_summit/SummitFlag00", "maggy/9_beyond_summit/checkpoint"],
        "bg": ["maggy/9_beyond_summit/cloud_a", "maggy/9_beyond_summit/cloud_c"],
    },
    "wind": {
        "fg": ["maggy/generic/grass_a", "maggy/generic/grass_b"],
        "bg": ["maggy/9_beyond_summit/cloud_d", "maggy/9_beyond_summit/cloud_e"],
    },
}


ROOM_STYLE_FLAGS: Dict[str, Dict[str, Any]] = {
    "wind": {"windPattern": "Left"},
    "space": {"space": True},
    "deepSpace": {"space": True, "dark": True},
    "void": {"space": True, "dark": True},
    "nightmare": {"dark": True},
    "cave": {"dark": True},
}


def _hazard_density(layout: str, hazard_chars: str) -> float:
    rows = layout.splitlines()
    if not rows:
        return 0.0
    walkable = sum(1 for row in rows for ch in row if ch != "3")
    if walkable <= 0:
        return 0.0
    hazards = sum(1 for row in rows for ch in row if ch in hazard_chars)
    return hazards / walkable


def _has_spawn_proxy(layout: str) -> bool:
    rows = layout.splitlines()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != "P":
                continue
            # Basic proxy: spawn must have at least one adjacent non-solid tile.
            neighbors = ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            for nx, ny in neighbors:
                if ny < 0 or ny >= len(rows):
                    continue
                if nx < 0 or nx >= len(rows[ny]):
                    continue
                if rows[ny][nx] != "3":
                    return True
    return False


def _ensure_spawn(layout: str) -> str:
    if "P" in layout and _has_spawn_proxy(layout):
        return layout
    rows = [list(row) for row in layout.splitlines()]
    if len(rows) < 2:
        return layout

    preferred = [(1, len(rows) - 2), (2, len(rows) - 2), (1, len(rows) - 3)]
    for x, y in preferred:
        if y < 0 or y >= len(rows):
            continue
        if x < 0 or x >= len(rows[y]):
            continue
        if rows[y][x] != "3":
            rows[y][x] = "P"
            return "\n".join("".join(r) for r in rows)
    return layout


def _load_pool(pool_path: Path) -> Dict[str, Any]:
    data = json.loads(pool_path.read_text(encoding="utf-8"))
    if "archetypes" not in data or not isinstance(data["archetypes"], list):
        raise ValueError("Pool JSON must contain an 'archetypes' array")
    return data


def _parse_rules(meta: Dict[str, Any]) -> SequenceRules:
    required_tags = {str(t) for t in meta.get("required_tags", [])}

    min_tag_counts: Dict[str, int] = {}
    raw_min = meta.get("min_tag_counts", {})
    if isinstance(raw_min, dict):
        for tag, count in raw_min.items():
            try:
                parsed = int(count)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                min_tag_counts[str(tag)] = parsed

    excluded_adjacent_tag_pairs: Set[Tuple[str, str]] = set()
    raw_pairs = meta.get("excluded_adjacent_tag_pairs", [])
    if isinstance(raw_pairs, list):
        for pair in raw_pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            a = str(pair[0])
            b = str(pair[1])
            excluded_adjacent_tag_pairs.add((a, b))
            excluded_adjacent_tag_pairs.add((b, a))

    late_game_tags = {str(t) for t in meta.get("late_game_tags", [])}
    try:
        late_game_start_ratio = float(meta.get("late_game_start_ratio", 0.6))
    except (TypeError, ValueError):
        late_game_start_ratio = 0.6
    late_game_start_ratio = max(0.0, min(1.0, late_game_start_ratio))

    return SequenceRules(
        required_tags=required_tags,
        min_tag_counts=min_tag_counts,
        excluded_adjacent_tag_pairs=excluded_adjacent_tag_pairs,
        late_game_tags=late_game_tags,
        late_game_start_ratio=late_game_start_ratio,
    )


def _parse_csv_tags(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _load_json_arg(raw: str, expected_type: type[Any], flag_name: str) -> Any:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {flag_name}: {exc.msg}") from exc
    if not isinstance(value, expected_type):
        raise ValueError(f"{flag_name} must decode to {expected_type.__name__}")
    return value


def _parse_min_tag_counts_arg(raw: str) -> Dict[str, int]:
    stripped = raw.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        parsed = _load_json_arg(stripped, dict, "--min-tag-counts")
        result: Dict[str, int] = {}
        for key, value in parsed.items():
            result[str(key)] = int(value)
        return result

    result: Dict[str, int] = {}
    for part in stripped.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError("--min-tag-counts must use JSON or tag=count pairs")
        key, value = item.split("=", 1)
        result[key.strip()] = int(value.strip())
    return result


def _parse_adjacent_pairs_arg(raw: str) -> List[List[str]]:
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        parsed = _load_json_arg(stripped, list, "--excluded-adjacent-tag-pairs")
        return [[str(pair[0]), str(pair[1])] for pair in parsed]

    result: List[List[str]] = []
    for part in stripped.split(","):
        item = part.strip()
        if not item:
            continue
        separator = ">" if ">" in item else ":"
        if separator not in item:
            raise ValueError(
                "--excluded-adjacent-tag-pairs must use JSON or tag>tag pairs"
            )
        left, right = item.split(separator, 1)
        result.append([left.strip(), right.strip()])
    return result


def _apply_rule_overrides(meta: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    merged = dict(meta)

    if args.required_tags:
        merged["required_tags"] = _parse_csv_tags(args.required_tags)
    if args.min_tag_counts:
        merged["min_tag_counts"] = _parse_min_tag_counts_arg(args.min_tag_counts)
    if args.excluded_adjacent_tag_pairs:
        merged["excluded_adjacent_tag_pairs"] = _parse_adjacent_pairs_arg(
            args.excluded_adjacent_tag_pairs
        )
    if args.late_game_tags:
        merged["late_game_tags"] = _parse_csv_tags(args.late_game_tags)
    if args.late_game_start_ratio not in (None, ""):
        try:
            merged["late_game_start_ratio"] = float(args.late_game_start_ratio)
        except ValueError as exc:
            raise ValueError("--late-game-start-ratio must be numeric") from exc

    return merged


def _parse_archetypes(data: Dict[str, Any], max_hazard_density: float) -> List[Archetype]:
    result: List[Archetype] = []
    for item in data["archetypes"]:
        layout = str(item["layout"])
        hazard_chars = str(item.get("hazard_chars", DEFAULT_HAZARD_CHARS))

        if _hazard_density(layout, hazard_chars) > max_hazard_density:
            continue

        result.append(
            Archetype(
                archetype_id=str(item["id"]),
                layout=layout,
                difficulty=int(item.get("difficulty", 1)),
                tags=[str(t) for t in item.get("tags", ["generic"])],
                weight=float(item.get("weight", 1.0)),
                open_left=bool(item.get("open_left", False)),
                open_right=bool(item.get("open_right", False)),
                hazard_chars=hazard_chars,
            )
        )

    if not result:
        raise ValueError("No archetypes left after validation. Relax constraints or update the pool.")
    return result


def _target_difficulty(index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return 1.0 + (index / (total - 1)) * 3.0


def _layout_dimensions(layout: str) -> Tuple[int, int]:
    rows = layout.splitlines()
    if not rows:
        return 0, 0
    return max(len(row) for row in rows), len(rows)


def _stable_index(text: str, modulo: int) -> int:
    if modulo <= 0:
        return 0
    return sum(ord(ch) for ch in text) % modulo


def _room_style(meta: Dict[str, Any], archetype: Archetype) -> str:
    style = str(meta.get("room_style", "")).strip().lower()
    if style:
        return style
    if "hazard" in archetype.tags or "finale" in archetype.tags:
        return "wind"
    return "normal"


def _decorated_entities(archetype: Archetype, width_tiles: int, height_tiles: int) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    room_w = width_tiles * 8
    room_h = height_tiles * 8

    if "dash" in archetype.tags:
        entities.append({
            "name": "booster",
            "x": max(16, room_w // 2),
            "y": max(16, room_h // 2 - 8),
            "red": "finale" in archetype.tags,
        })
    if "climb" in archetype.tags:
        entities.append({
            "name": "refill",
            "x": max(16, room_w - 24),
            "y": 20,
            "oneUse": False,
            "twoDash": False,
        })
    if "hazard" in archetype.tags and archetype.difficulty >= 3:
        entities.append({
            "name": "spring",
            "x": max(16, room_w - 32),
            "y": max(16, room_h - 16),
            "orientation": 0,
        })

    return entities


def _decorated_decals(archetype: Archetype, width_tiles: int, height_tiles: int, style: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    profile = DECAL_PROFILES.get(style, DECAL_PROFILES["normal"])
    room_w = width_tiles * 8
    room_h = height_tiles * 8

    fg_texture = profile["fg"][_stable_index(archetype.archetype_id, len(profile["fg"]))]
    bg_texture = profile["bg"][_stable_index(archetype.archetype_id + style, len(profile["bg"]))]

    fg = [
        {"texture": fg_texture, "x": max(0, room_w - 24), "y": max(0, room_h - 24)},
    ]
    bg = [
        {"texture": bg_texture, "x": max(8, room_w // 2 - 8), "y": 8},
    ]

    if "checkpoint" in archetype.tags:
        fg.append({"texture": "maggy/9_beyond_summit/checkpoint", "x": 8, "y": max(0, room_h - 24)})

    return fg, bg


def _room_visual_spec(archetype: Archetype, style: str) -> Dict[str, Any]:
    width_tiles, height_tiles = _layout_dimensions(archetype.layout)
    fgdecals, bgdecals = _decorated_decals(archetype, width_tiles, height_tiles, style)

    spec: Dict[str, Any] = {
        "solid_char": "3",
        "entities": _decorated_entities(archetype, width_tiles, height_tiles),
        "fgdecals": fgdecals,
        "bgdecals": bgdecals,
    }
    spec.update(ROOM_STYLE_FLAGS.get(style, {}))
    return spec


def _build_map_stylegrounds(meta: Dict[str, Any], sequence: Sequence[Archetype]) -> Dict[str, List[Dict[str, Any]]]:
    style = _room_style(meta, sequence[0]) if sequence else "normal"
    profile = STYLEGROUND_PROFILES.get(style, STYLEGROUND_PROFILES["normal"])
    return {
        "foregrounds": [dict(item) for item in profile.get("foregrounds", [])],
        "backgrounds": [dict(item) for item in profile.get("backgrounds", [])],
    }


def _violates_adjacent_rules(
    prev: Archetype | None,
    candidate: Archetype,
    excluded_adjacent_tag_pairs: Set[Tuple[str, str]],
) -> bool:
    if prev is None or not excluded_adjacent_tag_pairs:
        return False
    for left in prev.tags:
        for right in candidate.tags:
            if (left, right) in excluded_adjacent_tag_pairs:
                return True
    return False


def _score_candidate(
    candidate: Archetype,
    prev: Archetype | None,
    target_diff: float,
    used_counts: Dict[str, int],
    recent_tags: Sequence[str],
    current_tag_counts: Dict[str, int],
    index: int,
    room_count: int,
    rules: SequenceRules,
) -> float:
    if prev is not None and (not prev.open_right or not candidate.open_left):
        return 0.0
    if index < room_count - 1 and not candidate.open_right:
        return 0.0
    if _violates_adjacent_rules(prev, candidate, rules.excluded_adjacent_tag_pairs):
        return 0.0

    score = max(candidate.weight, 0.0)

    diff_gap = abs(candidate.difficulty - target_diff)
    score *= max(0.2, 1.2 - 0.25 * diff_gap)

    repeats = used_counts.get(candidate.archetype_id, 0)
    if repeats:
        score *= max(0.2, 1.0 - repeats * 0.35)

    overlap = len(set(candidate.tags).intersection(recent_tags))
    if overlap >= 2:
        score *= 0.5
    elif overlap == 1:
        score *= 0.8
    else:
        score *= 1.15

    missing_requirements = {
        tag for tag in rules.required_tags if current_tag_counts.get(tag, 0) <= 0
    }
    missing_minimums = {
        tag
        for tag, minimum in rules.min_tag_counts.items()
        if current_tag_counts.get(tag, 0) < minimum
    }
    needed_tags = missing_requirements.union(missing_minimums)
    if needed_tags and any(tag in needed_tags for tag in candidate.tags):
        score *= 1.35

    late_start = int((room_count - 1) * rules.late_game_start_ratio)
    is_late_slot = index >= late_start
    has_late_tag = any(tag in rules.late_game_tags for tag in candidate.tags)
    if rules.late_game_tags and has_late_tag:
        score *= 1.25 if is_late_slot else 0.75

    return score


def _weighted_choice(rng: random.Random, options: List[Archetype], scores: List[float]) -> Archetype:
    total = sum(scores)
    if total <= 0:
        return rng.choice(options)
    pick = rng.uniform(0, total)
    running = 0.0
    for archetype, score in zip(options, scores):
        running += score
        if running >= pick:
            return archetype
    return options[-1]


def _can_place(
    sequence: Sequence[Archetype],
    index: int,
    candidate: Archetype,
    rules: SequenceRules,
) -> bool:
    prev = sequence[index - 1] if index > 0 else None
    nxt = sequence[index + 1] if index + 1 < len(sequence) else None

    if prev is not None:
        if not prev.open_right or not candidate.open_left:
            return False
        if _violates_adjacent_rules(prev, candidate, rules.excluded_adjacent_tag_pairs):
            return False
    if nxt is not None:
        if not candidate.open_right or not nxt.open_left:
            return False
        if _violates_adjacent_rules(candidate, nxt, rules.excluded_adjacent_tag_pairs):
            return False
    return True


def _count_tags(sequence: Sequence[Archetype]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for archetype in sequence:
        for tag in archetype.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def _enforce_tag_requirements(
    sequence: List[Archetype],
    archetypes: Sequence[Archetype],
    rules: SequenceRules,
    rng: random.Random,
) -> None:
    deficits: Dict[str, int] = {}
    current = _count_tags(sequence)

    for tag in rules.required_tags:
        if current.get(tag, 0) <= 0:
            deficits[tag] = 1
    for tag, minimum in rules.min_tag_counts.items():
        have = current.get(tag, 0)
        if have < minimum:
            deficits[tag] = max(deficits.get(tag, 0), minimum - have)

    if not deficits:
        return

    for tag, needed in deficits.items():
        providers = [a for a in archetypes if tag in a.tags]
        if not providers:
            continue

        attempts = 0
        while needed > 0 and attempts < len(sequence) * 3:
            attempts += 1
            index = rng.randrange(max(1, len(sequence)))
            if index <= 0:
                continue
            if tag in sequence[index].tags:
                needed -= 1
                continue

            candidates = [
                a
                for a in providers
                if _can_place(sequence, index, a, rules)
            ]
            if not candidates:
                continue

            sequence[index] = rng.choice(candidates)
            needed -= 1


def generate_sequence(
    archetypes: Sequence[Archetype],
    room_count: int,
    rng: random.Random,
    rules: SequenceRules,
) -> List[Archetype]:
    if room_count <= 0:
        raise ValueError("room_count must be > 0")

    sequence: List[Archetype] = []
    used_counts: Dict[str, int] = {}
    current_tag_counts: Dict[str, int] = {}
    recent_tags: List[str] = []

    # Prefer explicit intro candidates for the first room.
    intro_candidates = [a for a in archetypes if "intro" in a.tags] or list(archetypes)
    if room_count > 1:
        intro_candidates = [a for a in intro_candidates if a.open_right] or intro_candidates
    first = rng.choice(intro_candidates)
    sequence.append(first)
    used_counts[first.archetype_id] = 1
    for tag in first.tags:
        current_tag_counts[tag] = current_tag_counts.get(tag, 0) + 1
    recent_tags = first.tags[-2:]

    while len(sequence) < room_count:
        index = len(sequence)
        target_diff = _target_difficulty(index, room_count)
        prev = sequence[-1]

        options = list(archetypes)
        scores = [
            _score_candidate(
                c,
                prev,
                target_diff,
                used_counts,
                recent_tags,
                current_tag_counts,
                index,
                room_count,
                rules,
            )
            for c in options
        ]

        pick = _weighted_choice(rng, options, scores)
        sequence.append(pick)
        used_counts[pick.archetype_id] = used_counts.get(pick.archetype_id, 0) + 1
        for tag in pick.tags:
            current_tag_counts[tag] = current_tag_counts.get(tag, 0) + 1
        recent_tags = (recent_tags + pick.tags)[-4:]

    _enforce_tag_requirements(sequence, archetypes, rules, rng)

    # Prefer a checkpoint marker in the second half.
    has_checkpoint = any("C" in a.layout for a in sequence)
    if not has_checkpoint:
        second_half = list(range(max(1, room_count // 2), room_count))
        if second_half:
            idx = rng.choice(second_half)
            rows = [list(row) for row in sequence[idx].layout.splitlines()]
            for y in range(len(rows) - 2, 0, -1):
                for x in range(1, len(rows[y]) - 1):
                    if rows[y][x] == " ":
                        rows[y][x] = "C"
                        updated = "\n".join("".join(r) for r in rows)
                        replacement = Archetype(
                            archetype_id=sequence[idx].archetype_id,
                            layout=updated,
                            difficulty=sequence[idx].difficulty,
                            tags=sequence[idx].tags,
                            weight=sequence[idx].weight,
                            open_left=sequence[idx].open_left,
                            open_right=sequence[idx].open_right,
                            hazard_chars=sequence[idx].hazard_chars,
                        )
                        sequence[idx] = replacement
                        second_half = []
                        break
                if not second_half:
                    break

    return sequence


def build_custom_rooms(sequence: Sequence[Archetype], room_prefix: str) -> List[Dict[str, Any]]:
    rooms: List[Dict[str, Any]] = []
    x = 0
    for i, archetype in enumerate(sequence):
        name = f"room_{i:02d}_{archetype.archetype_id}"
        if room_prefix:
            name = f"{room_prefix}{name}"

        layout = archetype.layout
        if i == 0:
            layout = _ensure_spawn(layout)

        rooms.append({
            "name": name,
            "x": x,
            "y": 0,
            "layout": layout,
        })
        x += 128

    return rooms


def build_custom_map(sequence: Sequence[Archetype], room_prefix: str, meta: Dict[str, Any] | None = None) -> Dict[str, Any]:
    meta = meta or {}
    rooms: List[Dict[str, Any]] = []
    x = 0
    for i, archetype in enumerate(sequence):
        name = f"room_{i:02d}_{archetype.archetype_id}"
        if room_prefix:
            name = f"{room_prefix}{name}"

        layout = archetype.layout
        if i == 0:
            layout = _ensure_spawn(layout)

        style = _room_style(meta, archetype)
        spec = _room_visual_spec(archetype, style)
        spec.update({
            "name": name,
            "x": x,
            "y": 0,
            "layout": layout,
        })
        rooms.append(spec)
        width_tiles, _ = _layout_dimensions(layout)
        x += width_tiles * 8

    return {
        "rooms": rooms,
        "stylegrounds": _build_map_stylegrounds(meta, sequence),
    }


def _build_sequence_report(
    sequence: Sequence[Archetype],
    rules: SequenceRules,
    seed: int | None,
    pool_path: Path,
    room_prefix: str,
) -> Dict[str, Any]:
    tag_counts = _count_tags(sequence)
    adjacency_violations: List[Dict[str, Any]] = []
    for index in range(1, len(sequence)):
        prev = sequence[index - 1]
        current = sequence[index]
        if _violates_adjacent_rules(prev, current, rules.excluded_adjacent_tag_pairs):
            adjacency_violations.append(
                {
                    "index": index,
                    "prev": prev.archetype_id,
                    "current": current.archetype_id,
                    "prev_tags": prev.tags,
                    "current_tags": current.tags,
                }
            )

    late_start_index = int((len(sequence) - 1) * rules.late_game_start_ratio) if sequence else 0
    late_game_rooms = [
        {
            "index": index,
            "archetype_id": archetype.archetype_id,
            "tags": archetype.tags,
            "is_late_slot": index >= late_start_index,
        }
        for index, archetype in enumerate(sequence)
        if any(tag in rules.late_game_tags for tag in archetype.tags)
    ]

    return {
        "seed": seed,
        "pool_path": str(pool_path),
        "room_prefix": room_prefix,
        "room_count": len(sequence),
        "sequence_ids": [archetype.archetype_id for archetype in sequence],
        "rooms": [
            {
                "index": index,
                "archetype_id": archetype.archetype_id,
                "difficulty": archetype.difficulty,
                "tags": archetype.tags,
                "open_left": archetype.open_left,
                "open_right": archetype.open_right,
                "hazard_density": round(_hazard_density(archetype.layout, archetype.hazard_chars), 4),
                "contains_checkpoint": "C" in archetype.layout,
            }
            for index, archetype in enumerate(sequence)
        ],
        "tag_counts": dict(sorted(tag_counts.items())),
        "rules": {
            "required_tags": sorted(rules.required_tags),
            "min_tag_counts": rules.min_tag_counts,
            "excluded_adjacent_tag_pairs": sorted(list(rules.excluded_adjacent_tag_pairs)),
            "late_game_tags": sorted(rules.late_game_tags),
            "late_game_start_ratio": rules.late_game_start_ratio,
            "late_game_start_index": late_start_index,
        },
        "constraint_status": {
            "required_tags": {
                tag: tag_counts.get(tag, 0) > 0 for tag in sorted(rules.required_tags)
            },
            "min_tag_counts": {
                tag: {
                    "required": minimum,
                    "actual": tag_counts.get(tag, 0),
                    "satisfied": tag_counts.get(tag, 0) >= minimum,
                }
                for tag, minimum in sorted(rules.min_tag_counts.items())
            },
            "excluded_adjacent_violations": adjacency_violations,
            "late_game_rooms": late_game_rooms,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate custom room JSON from a weighted archetype pool."
    )
    parser.add_argument("output_json", help="Path to write generated custom rooms JSON")
    parser.add_argument(
        "--pool",
        default=str(Path(__file__).with_name("pcg_room_pool.example.json")),
        help="Path to room pool JSON",
    )
    parser.add_argument("--rooms", type=int, default=7, help="Number of rooms to generate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--room-prefix", default="", help="Optional room name prefix")
    parser.add_argument(
        "--required-tags",
        default="",
        help="Optional comma-separated override for required_tags",
    )
    parser.add_argument(
        "--min-tag-counts",
        default="",
        help="Optional JSON object override for min_tag_counts",
    )
    parser.add_argument(
        "--excluded-adjacent-tag-pairs",
        default="",
        help="Optional JSON array override for excluded_adjacent_tag_pairs",
    )
    parser.add_argument(
        "--late-game-tags",
        default="",
        help="Optional comma-separated override for late_game_tags",
    )
    parser.add_argument(
        "--late-game-start-ratio",
        default="",
        help="Optional override for late_game_start_ratio",
    )
    parser.add_argument(
        "--report-out",
        default="",
        help="Optional path to write a JSON sequence report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_json).resolve()
    pool_path = Path(args.pool).resolve()

    data = _load_pool(pool_path)
    meta = _apply_rule_overrides(data.get("meta", {}), args)
    max_hazard_density = float(meta.get("max_hazard_density", 0.16))
    rules = _parse_rules(meta)

    archetypes = _parse_archetypes(data, max_hazard_density=max_hazard_density)
    rng = random.Random(args.seed)

    sequence = generate_sequence(archetypes, room_count=args.rooms, rng=rng, rules=rules)
    custom_map = build_custom_map(sequence, room_prefix=args.room_prefix, meta=meta)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(custom_map, indent=2), encoding="utf-8")

    if args.report_out:
        report_path = Path(args.report_out).resolve()
        report = _build_sequence_report(
            sequence,
            rules=rules,
            seed=args.seed,
            pool_path=pool_path,
            room_prefix=args.room_prefix,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {report_path}")

    archetype_ids = ", ".join(s.archetype_id for s in sequence)
    print(f"Wrote {len(custom_map['rooms'])} rooms -> {output_path}")
    print(f"Seed: {args.seed}")
    print(f"Sequence: {archetype_ids}")


if __name__ == "__main__":
    main()
