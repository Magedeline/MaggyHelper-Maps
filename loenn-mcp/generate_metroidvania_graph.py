#!/usr/bin/env python3
"""Solve a metroidvania graph spec into loenn-mcp custom room JSON."""

from __future__ import annotations

import argparse
import importlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


def _import_weighted_module():
    return importlib.import_module("generate_weighted_room_sequence")


weighted = _import_weighted_module()


@dataclass(frozen=True)
class TemplateDef:
    template_id: str
    zone: str
    weight: float
    difficulty: int
    tags: List[str]
    layout: str
    hazard_chars: str
    supports_beats: List[str]
    entrance_requirements: List[dict[str, Any]]
    exits: List[dict[str, Any]]
    reward_slots: List[dict[str, Any]]
    entities: List[dict[str, Any]]
    fgdecals: List[dict[str, Any]]
    bgdecals: List[dict[str, Any]]
    room_flags: Dict[str, Any]


@dataclass(frozen=True)
class BeatDef:
    beat_id: str
    kind: str
    zone: str
    requires: List[dict[str, Any]]
    grants_item: str
    grants_ability: str
    opens_lock: str
    allowed_room_tags: List[str]
    preferred_templates: List[str]
    critical: bool


@dataclass
class SolverState:
    abilities: set[str]
    items: set[str]
    flags: set[str]
    opened_locks: set[str]
    completed_beats: list[str]
    visited_tags: list[str]

    def snapshot(self) -> Dict[str, list[str]]:
        return {
            "abilities": sorted(self.abilities),
            "items": sorted(self.items),
            "flags": sorted(self.flags),
            "opened_locks": sorted(self.opened_locks),
            "completed_beats": list(self.completed_beats),
            "visited_tags": list(self.visited_tags),
        }


def _state_from_snapshot(snapshot: Dict[str, list[str]]) -> SolverState:
    return SolverState(
        abilities=set(snapshot.get("abilities", [])),
        items=set(snapshot.get("items", [])),
        flags=set(snapshot.get("flags", [])),
        opened_locks=set(snapshot.get("opened_locks", [])),
        completed_beats=list(snapshot.get("completed_beats", [])),
        visited_tags=list(snapshot.get("visited_tags", [])),
    )


@dataclass(frozen=True)
class SolvedRoom:
    kind: str
    node_id: str
    zone: str
    template: TemplateDef
    state_before: Dict[str, list[str]]
    state_after: Dict[str, list[str]]


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Graph spec must be a JSON object")
    return data


def _normalize_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _index_by_id(items: Iterable[dict[str, Any]], kind: str) -> Dict[str, dict[str, Any]]:
    result: Dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise ValueError(f"Each {kind} needs a non-empty id")
        if item_id in result:
            raise ValueError(f"Duplicate {kind} id: {item_id}")
        result[item_id] = item
    return result


def _parse_templates(spec: Dict[str, Any]) -> List[TemplateDef]:
    meta = spec.get("meta", {})
    default_hazard_chars = str(meta.get("default_hazard_chars", weighted.DEFAULT_HAZARD_CHARS))
    placement_rules = spec.get("placement_rules", {})
    max_hazard_density = float(placement_rules.get("max_hazard_density", 0.16))

    templates: List[TemplateDef] = []
    for raw in spec.get("room_templates", []):
        if not isinstance(raw, dict):
            continue
        layout = str(raw.get("layout", ""))
        if not layout.strip():
            continue
        hazard_chars = str(raw.get("hazard_chars", default_hazard_chars))
        if weighted._hazard_density(layout, hazard_chars) > max_hazard_density:
            continue
        templates.append(
            TemplateDef(
                template_id=str(raw.get("id", "")).strip(),
                zone=str(raw.get("zone", "")).strip(),
                weight=float(raw.get("weight", 1.0)),
                difficulty=int(raw.get("difficulty", 1)),
                tags=_normalize_str_list(raw.get("tags", [])),
                layout=layout,
                hazard_chars=hazard_chars,
                supports_beats=_normalize_str_list(raw.get("supports_beats", [])),
                entrance_requirements=[
                    item for item in raw.get("entrance_requirements", []) if isinstance(item, dict)
                ],
                exits=[item for item in raw.get("exits", []) if isinstance(item, dict)],
                reward_slots=[item for item in raw.get("reward_slots", []) if isinstance(item, dict)],
                entities=[item for item in raw.get("entities", []) if isinstance(item, dict)],
                fgdecals=[item for item in raw.get("fgdecals", []) if isinstance(item, dict)],
                bgdecals=[item for item in raw.get("bgdecals", []) if isinstance(item, dict)],
                room_flags=dict(raw.get("room_flags", {})) if isinstance(raw.get("room_flags", {}), dict) else {},
            )
        )

    templates = [template for template in templates if template.template_id]
    if not templates:
        raise ValueError("No room templates remain after validation")
    return templates


def _parse_beats(spec: Dict[str, Any]) -> List[BeatDef]:
    graph = spec.get("graph", {})
    beats: List[BeatDef] = []
    for raw in graph.get("beats", []):
        if not isinstance(raw, dict):
            continue
        beat_id = str(raw.get("id", "")).strip()
        kind = str(raw.get("kind", "")).strip()
        if not beat_id or not kind:
            continue
        beats.append(
            BeatDef(
                beat_id=beat_id,
                kind=kind,
                zone=str(raw.get("zone", "")).strip(),
                requires=[item for item in raw.get("requires", []) if isinstance(item, dict)],
                grants_item=str(raw.get("grants_item", "")).strip(),
                grants_ability=str(raw.get("grants_ability", "")).strip(),
                opens_lock=str(raw.get("opens_lock", "")).strip(),
                allowed_room_tags=_normalize_str_list(raw.get("allowed_room_tags", [])),
                preferred_templates=_normalize_str_list(raw.get("preferred_templates", [])),
                critical=bool(raw.get("critical", True)),
            )
        )
    if not beats:
        raise ValueError("Graph spec must contain at least one beat")
    return beats


def _validate_graph_order(spec: Dict[str, Any], beats: Sequence[BeatDef]) -> None:
    graph = spec.get("graph", {})
    start = str(graph.get("start", "")).strip()
    goal = str(graph.get("goal", "")).strip()
    beat_ids = [beat.beat_id for beat in beats]
    if start not in beat_ids:
        raise ValueError(f"Graph start beat not found: {start}")
    if goal not in beat_ids:
        raise ValueError(f"Graph goal beat not found: {goal}")
    if beat_ids[0] != start:
        raise ValueError("Graph start must be the first beat in graph.beats for this generator")
    if beat_ids[-1] != goal:
        raise ValueError("Graph goal must be the last beat in graph.beats for this generator")


def _initial_state(spec: Dict[str, Any]) -> SolverState:
    abilities = {
        str(item.get("id"))
        for item in spec.get("abilities", [])
        if isinstance(item, dict) and item.get("starts_unlocked")
    }
    return SolverState(
        abilities=abilities,
        items=set(),
        flags=set(),
        opened_locks=set(),
        completed_beats=[],
        visited_tags=[],
    )


def _requirement_satisfied(requirement: Dict[str, Any], state: SolverState) -> bool:
    if "ability" in requirement:
        return str(requirement["ability"]) in state.abilities
    if "item" in requirement:
        return str(requirement["item"]) in state.items
    if "flag" in requirement:
        return str(requirement["flag"]) in state.flags
    if "event" in requirement:
        return str(requirement["event"]) in state.completed_beats
    if "tag" in requirement:
        return str(requirement["tag"]) in state.visited_tags
    if "all" in requirement:
        values = requirement.get("all", [])
        return bool(values) and all(
            _requirement_satisfied(item, state)
            for item in values
            if isinstance(item, dict)
        )
    if "any" in requirement:
        values = requirement.get("any", [])
        return any(
            _requirement_satisfied(item, state)
            for item in values
            if isinstance(item, dict)
        )
    if "not" in requirement and isinstance(requirement.get("not"), dict):
        return not _requirement_satisfied(requirement["not"], state)
    return False


def _requirements_satisfied(requirements: Sequence[Dict[str, Any]], state: SolverState) -> bool:
    return all(_requirement_satisfied(requirement, state) for requirement in requirements)


def _parse_excluded_pairs(spec: Dict[str, Any]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    placement_rules = spec.get("placement_rules", {})
    for pair in placement_rules.get("excluded_adjacent_tag_pairs", []):
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        left = str(pair[0])
        right = str(pair[1])
        result.add((left, right))
        result.add((right, left))
    return result


def _template_to_archetype(template: TemplateDef):
    exit_sides = {str(item.get("side", "")).strip() for item in template.exits}
    return weighted.Archetype(
        archetype_id=template.template_id,
        layout=template.layout,
        difficulty=template.difficulty,
        tags=list(template.tags),
        weight=template.weight,
        open_left="left" in exit_sides,
        open_right="right" in exit_sides,
        hazard_chars=template.hazard_chars,
    )


def _score_template(
    template: TemplateDef,
    beat: BeatDef,
    prev_template: TemplateDef | None,
    index: int,
    total: int,
    state: SolverState,
    used_counts: Dict[str, int],
    excluded_pairs: set[tuple[str, str]],
    placement_rules: Dict[str, Any],
) -> float:
    if beat.zone and template.zone and beat.zone != template.zone:
        return 0.0
    if template.entrance_requirements and not _requirements_satisfied(template.entrance_requirements, state):
        return 0.0
    if beat.allowed_room_tags and not set(template.tags).intersection(beat.allowed_room_tags):
        return 0.0
    if prev_template is not None:
        prev_archetype = _template_to_archetype(prev_template)
        current_archetype = _template_to_archetype(template)
        if weighted._violates_adjacent_rules(
            prev_archetype, current_archetype, excluded_pairs
        ):
            return 0.0

    score = max(template.weight, 0.05)

    if beat.zone and template.zone == beat.zone:
        score *= 1.4
    if beat.kind in template.supports_beats:
        score *= 1.35
    elif template.supports_beats:
        score *= 0.7

    if beat.preferred_templates:
        if template.template_id in beat.preferred_templates:
            score *= 3.0
        else:
            score *= 0.7

    if beat.allowed_room_tags:
        overlap = len(set(template.tags).intersection(beat.allowed_room_tags))
        score *= 1.0 + overlap * 0.2

    target_diff = 1.0 if total <= 1 else 1.0 + (index / (total - 1)) * 5.0
    diff_gap = abs(template.difficulty - target_diff)
    score *= max(0.25, 1.15 - diff_gap * 0.18)

    repeats = used_counts.get(template.template_id, 0)
    if repeats:
        score *= max(0.25, 1.0 - repeats * 0.35)

    late_game_tags = set(_normalize_str_list(placement_rules.get("late_game_tags", [])))
    late_game_start_ratio = float(placement_rules.get("late_game_start_ratio", 0.6))
    late_start_index = int(max(0, total - 1) * late_game_start_ratio)
    is_late_slot = index >= late_start_index
    has_late_tag = any(tag in late_game_tags for tag in template.tags)
    if late_game_tags and has_late_tag:
        score *= 1.2 if is_late_slot else 0.8

    if any(tag in {"boss", "goal"} for tag in template.tags) and beat.kind not in {"boss", "goal"}:
        score *= 0.4
    if beat.kind == "start" and "intro" in template.tags:
        score *= 1.5

    return score


def _weighted_pick(rng: random.Random, options: Sequence[TemplateDef], scores: Sequence[float]) -> TemplateDef:
    total = sum(scores)
    if total <= 0:
        return rng.choice(list(options))
    pick = rng.uniform(0, total)
    running = 0.0
    for option, score in zip(options, scores):
        running += score
        if running >= pick:
            return option
    return options[-1]


def _choose_template_for_beat(
    templates: Sequence[TemplateDef],
    beat: BeatDef,
    prev_template: TemplateDef | None,
    index: int,
    total: int,
    state: SolverState,
    used_counts: Dict[str, int],
    rng: random.Random,
    spec: Dict[str, Any],
) -> TemplateDef:
    placement_rules = spec.get("placement_rules", {})
    excluded_pairs = _parse_excluded_pairs(spec)
    scores = [
        _score_template(
            template,
            beat,
            prev_template,
            index,
            total,
            state,
            used_counts,
            excluded_pairs,
            placement_rules,
        )
        for template in templates
    ]
    viable = [(template, score) for template, score in zip(templates, scores) if score > 0]
    if not viable:
        raise ValueError(
            f"No room template can satisfy beat '{beat.beat_id}' with current state {state.snapshot()}"
        )
    options = [template for template, _ in viable]
    option_scores = [score for _, score in viable]
    return _weighted_pick(rng, options, option_scores)


def _choose_filler_template(
    templates: Sequence[TemplateDef],
    prev_template: TemplateDef,
    next_beat: BeatDef,
    state: SolverState,
    used_counts: Dict[str, int],
    rng: random.Random,
    spec: Dict[str, Any],
) -> TemplateDef:
    placement_rules = spec.get("placement_rules", {})
    excluded_pairs = _parse_excluded_pairs(spec)

    options: List[TemplateDef] = []
    scores: List[float] = []
    for template in templates:
        if template.entrance_requirements and not _requirements_satisfied(template.entrance_requirements, state):
            continue
        if next_beat.zone and template.zone and template.zone != next_beat.zone and prev_template.zone != template.zone:
            continue

        score = max(template.weight, 0.05)
        if set(template.tags).intersection({"boss", "goal", "intro"}):
            score *= 0.35
        if template.zone and template.zone == prev_template.zone:
            score *= 1.25
        if next_beat.zone and template.zone == next_beat.zone:
            score *= 1.15

        prev_archetype = _template_to_archetype(prev_template)
        current_archetype = _template_to_archetype(template)
        if weighted._violates_adjacent_rules(prev_archetype, current_archetype, excluded_pairs):
            continue

        repeats = used_counts.get(template.template_id, 0)
        if repeats:
            score *= max(0.3, 1.0 - repeats * 0.25)
        if template.supports_beats:
            score *= 0.8
        options.append(template)
        scores.append(score)

    if not options:
        return prev_template
    return _weighted_pick(rng, options, scores)


def _apply_item_grants(item_id: str, items_by_id: Dict[str, dict[str, Any]], state: SolverState) -> None:
    item = items_by_id.get(item_id)
    if item is None:
        raise ValueError(f"Unknown item id: {item_id}")
    state.items.add(item_id)
    for ability_id in _normalize_str_list(item.get("grants_abilities", [])):
        state.abilities.add(ability_id)
    for flag_id in _normalize_str_list(item.get("sets_flags", [])):
        state.flags.add(flag_id)


def _apply_lock_open(lock_id: str, locks_by_id: Dict[str, dict[str, Any]], state: SolverState) -> None:
    lock = locks_by_id.get(lock_id)
    if lock is None:
        raise ValueError(f"Unknown lock id: {lock_id}")
    for requirement in lock.get("requires", []):
        if isinstance(requirement, dict) and not _requirement_satisfied(requirement, state):
            raise ValueError(f"Lock '{lock_id}' cannot be opened with current state")
    if isinstance(lock.get("requires"), dict) and not _requirement_satisfied(lock["requires"], state):
        raise ValueError(f"Lock '{lock_id}' cannot be opened with current state")
    state.opened_locks.add(lock_id)
    for flag_id in _normalize_str_list(lock.get("sets_flags_on_open", [])):
        state.flags.add(flag_id)
    for item_id in _normalize_str_list(lock.get("consumes_items", [])):
        state.items.discard(item_id)


def _apply_beat_grants(
    beat: BeatDef,
    items_by_id: Dict[str, dict[str, Any]],
    locks_by_id: Dict[str, dict[str, Any]],
    state: SolverState,
) -> None:
    state.completed_beats.append(beat.beat_id)
    if beat.grants_ability:
        state.abilities.add(beat.grants_ability)
    if beat.grants_item:
        _apply_item_grants(beat.grants_item, items_by_id, state)
    if beat.opens_lock:
        _apply_lock_open(beat.opens_lock, locks_by_id, state)


def _target_room_count(spec: Dict[str, Any], beat_count: int) -> int:
    graph = spec.get("graph", {})
    room_budget = graph.get("room_budget", {})
    critical_path = graph.get("critical_path_length", {})
    targets = [beat_count]
    if isinstance(room_budget, dict) and room_budget.get("target") is not None:
        targets.append(int(room_budget["target"]))
    if isinstance(critical_path, dict) and critical_path.get("target") is not None:
        targets.append(int(critical_path["target"]))
    return max(targets)


def solve_graph(spec: Dict[str, Any], seed: int | None = None) -> List[SolvedRoom]:
    templates = _parse_templates(spec)
    beats = _parse_beats(spec)
    _validate_graph_order(spec, beats)

    items_by_id = _index_by_id(spec.get("items", []), "item")
    locks_by_id = _index_by_id(spec.get("locks", []), "lock")
    state = _initial_state(spec)
    rng_seed = seed if seed is not None else spec.get("meta", {}).get("seed")
    rng = random.Random(rng_seed)

    solved: List[SolvedRoom] = []
    used_counts: Dict[str, int] = {}
    prev_template: TemplateDef | None = None

    for index, beat in enumerate(beats):
        if not _requirements_satisfied(beat.requires, state):
            raise ValueError(
                f"Beat '{beat.beat_id}' is not reachable with current state {state.snapshot()}"
            )
        before = state.snapshot()
        template = _choose_template_for_beat(
            templates,
            beat,
            prev_template,
            index,
            len(beats),
            state,
            used_counts,
            rng,
            spec,
        )
        state.visited_tags.extend(template.tags)
        _apply_beat_grants(beat, items_by_id, locks_by_id, state)
        after = state.snapshot()
        solved.append(
            SolvedRoom(
                kind=beat.kind,
                node_id=beat.beat_id,
                zone=beat.zone or template.zone,
                template=template,
                state_before=before,
                state_after=after,
            )
        )
        used_counts[template.template_id] = used_counts.get(template.template_id, 0) + 1
        prev_template = template

    target_room_count = _target_room_count(spec, len(solved))
    if target_room_count > len(solved) and solved:
        filler_budget = target_room_count - len(solved)
        gap_count = max(1, len(solved) - 1)
        inserts_per_gap = [0] * gap_count
        for index in range(filler_budget):
            inserts_per_gap[index % gap_count] += 1

        expanded: List[SolvedRoom] = []
        for index, solved_room in enumerate(solved[:-1]):
            expanded.append(solved_room)
            next_room = solved[index + 1]
            for filler_index in range(inserts_per_gap[index]):
                gap_state = _state_from_snapshot(solved_room.state_after)
                filler_template = _choose_filler_template(
                    templates,
                    expanded[-1].template,
                    beats[index + 1],
                    gap_state,
                    used_counts,
                    rng,
                    spec,
                )
                filler_id = f"transit_{index:02d}_{filler_index:02d}_{filler_template.template_id}"
                expanded.append(
                    SolvedRoom(
                        kind="transit",
                        node_id=filler_id,
                        zone=filler_template.zone,
                        template=filler_template,
                        state_before=gap_state.snapshot(),
                        state_after=gap_state.snapshot(),
                    )
                )
                used_counts[filler_template.template_id] = used_counts.get(filler_template.template_id, 0) + 1
            
        expanded.append(solved[-1])
        solved = expanded

    return solved


def _merge_entities(*groups: Sequence[dict[str, Any]]) -> List[dict[str, Any]]:
    merged: List[dict[str, Any]] = []
    for group in groups:
        for item in group:
            if isinstance(item, dict):
                merged.append(dict(item))
    return merged


def build_custom_map(
    solved_rooms: Sequence[SolvedRoom],
    spec: Dict[str, Any],
    room_prefix: str = "",
) -> Dict[str, Any]:
    meta = dict(spec.get("meta", {}))
    render_defaults = spec.get("render_defaults", {})
    render_room_flags = dict(render_defaults.get("room_flags", {})) if isinstance(render_defaults, dict) else {}
    render_stylegrounds = render_defaults.get("stylegrounds") if isinstance(render_defaults, dict) else None

    rooms: List[Dict[str, Any]] = []
    x = 0
    sequence_archetypes = []

    for index, solved_room in enumerate(solved_rooms):
        template = solved_room.template
        archetype = _template_to_archetype(template)
        sequence_archetypes.append(archetype)
        style = weighted._room_style(meta, archetype)
        visual_spec = weighted._room_visual_spec(archetype, style)
        layout = template.layout
        if index == 0:
            layout = weighted._ensure_spawn(layout)

        name = f"room_{index:02d}_{solved_room.node_id}_{template.template_id}"
        if room_prefix:
            name = f"{room_prefix}{name}"

        room_spec: Dict[str, Any] = {
            "name": name,
            "x": x,
            "y": 0,
            "layout": layout,
            "solid_char": visual_spec.get("solid_char", "3"),
            "entities": _merge_entities(visual_spec.get("entities", []), template.entities),
            "fgdecals": _merge_entities(visual_spec.get("fgdecals", []), template.fgdecals),
            "bgdecals": _merge_entities(visual_spec.get("bgdecals", []), template.bgdecals),
        }

        for key, value in render_room_flags.items():
            room_spec[key] = value
        for key, value in visual_spec.items():
            if key in {"solid_char", "entities", "fgdecals", "bgdecals"}:
                continue
            room_spec[key] = value
        for key, value in template.room_flags.items():
            room_spec[key] = value

        rooms.append(room_spec)
        width_tiles, _ = weighted._layout_dimensions(layout)
        x += width_tiles * 8

    if isinstance(render_stylegrounds, dict):
        stylegrounds = {
            "foregrounds": list(render_stylegrounds.get("foregrounds", [])),
            "backgrounds": list(render_stylegrounds.get("backgrounds", [])),
        }
    else:
        stylegrounds = weighted._build_map_stylegrounds(meta, sequence_archetypes)

    return {
        "rooms": rooms,
        "stylegrounds": stylegrounds,
    }


def _build_solver_report(
    solved_rooms: Sequence[SolvedRoom],
    spec_path: Path,
    spec: Dict[str, Any],
    seed: int | None,
    room_prefix: str,
) -> Dict[str, Any]:
    graph = spec.get("graph", {})
    return {
        "spec_path": str(spec_path),
        "seed": seed if seed is not None else spec.get("meta", {}).get("seed"),
        "room_prefix": room_prefix,
        "graph_start": graph.get("start"),
        "graph_goal": graph.get("goal"),
        "room_count": len(solved_rooms),
        "sequence_ids": [room.node_id for room in solved_rooms],
        "rooms": [
            {
                "index": index,
                "kind": room.kind,
                "node_id": room.node_id,
                "zone": room.zone,
                "template_id": room.template.template_id,
                "difficulty": room.template.difficulty,
                "tags": room.template.tags,
                "state_before": room.state_before,
                "state_after": room.state_after,
            }
            for index, room in enumerate(solved_rooms)
        ],
    }


def build_custom_map_from_spec_file(
    spec_path: Path,
    seed: int | None = None,
    room_prefix: str = "",
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    spec = _load_json(spec_path)
    solved_rooms = solve_graph(spec, seed=seed)
    custom_map = build_custom_map(solved_rooms, spec, room_prefix=room_prefix)
    report = _build_solver_report(solved_rooms, spec_path, spec, seed, room_prefix)
    return custom_map, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate loenn-mcp custom room JSON from a metroidvania graph spec."
    )
    parser.add_argument("output_json", help="Path to write generated custom room JSON")
    parser.add_argument(
        "--spec",
        default=str(Path(__file__).with_name("metroidvania_graph.example.json")),
        help="Path to metroidvania graph spec JSON",
    )
    parser.add_argument("--seed", type=int, default=None, help="Optional random seed override")
    parser.add_argument("--room-prefix", default="", help="Optional prefix applied to room names")
    parser.add_argument("--report-out", default="", help="Optional solver report JSON path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_json).resolve()
    spec_path = Path(args.spec).resolve()

    custom_map, report = build_custom_map_from_spec_file(
        spec_path,
        seed=args.seed,
        room_prefix=args.room_prefix,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(custom_map, indent=2), encoding="utf-8")

    if args.report_out:
        report_path = Path(args.report_out).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {report_path}")

    print(f"Wrote {len(custom_map['rooms'])} rooms -> {output_path}")
    print("Sequence: " + ", ".join(report["sequence_ids"]))


if __name__ == "__main__":
    main()