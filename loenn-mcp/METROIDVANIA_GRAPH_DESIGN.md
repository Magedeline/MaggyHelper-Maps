# Metroidvania Graph Workflow

This document defines a larger procedural workflow for `loenn-mcp` that is closer to the graph-first, gated structure shown in Aran Ink's metroidvania generation notes.

The current weighted workflow in this repository is good at pacing a linear chain of rooms. It does not yet plan ability gates, hubs, revisits, shortcuts, or solver-verified progression. This spec is meant to close that gap without throwing away the existing `generate_weighted_room_sequence.py` and `generate_weighted_and_preview.py` path.

## Design goals

1. Plan progression before geometry.
2. Treat rooms as hand-authored templates, not disposable noise.
3. Encode gates explicitly with ability, item, flag, and lock requirements.
4. Validate reachability with a progression solver before exporting Celeste room JSON.
5. Preserve compatibility with the current `custom_rooms_json` output shape so the final step still runs through `generate_starter_map`.

## New files

- `metroidvania_graph.schema.json`: schema for the full graph-first input format.
- `metroidvania_graph.example.json`: example content covering zones, beats, locks, items, and template exits.

## Core model

The graph workflow is built from these layers:

1. `room_templates`
Hand-authored rooms with exits, tags, reward slots, and optional visual defaults.

2. `graph.beats`
Progression milestones such as start, ability pickup, lock, checkpoint, shortcut, boss, and goal.

3. `abilities`, `items`, and `locks`
The progression state model. This is what the solver reasons about.

4. `zones`
Large-scale structure for local style, pacing, and adjacency preferences.

5. `placement_rules`
Scoring and filtering rules reused from the current weighted pipeline, extended to non-linear placement.

6. `validation`
Rules the solver must satisfy before a result is allowed to emit rooms.

## Intended generation pipeline

### Phase 1: load and normalize

- Parse the graph spec.
- Expand defaults from `meta`, `placement_rules`, and `render_defaults`.
- Precompute template stats such as dimensions, exits, and hazard density.

### Phase 2: build abstract progression graph

- Create a beat graph from `graph.beats`.
- Place critical beats on a main route from `graph.start` to `graph.goal`.
- Insert optional side paths from `graph.branch_budget`.
- Prefer zones in `graph.zone_order`, while respecting `zones[].preferred_neighbors`.

### Phase 3: assign templates to beats and transit nodes

- Match each beat to templates via `preferred_templates`, `allowed_room_tags`, and `supports_beats`.
- Add transit or hub rooms between beats to satisfy target path length.
- Match exits by side and by `connects_to_tags`.
- Reject local placements that violate adjacency, density, or duplication rules.

### Phase 4: solve progression

- Start with `starts_unlocked` abilities.
- Traverse exits whose `requires` arrays and `lock_id` conditions are currently satisfied.
- When a beat or reward slot grants an item, update the solver state.
- Confirm that every critical beat can be reached in an order that does not deadlock.

### Phase 5: emit Celeste rooms

- Convert the solved graph into ordered room instances with coordinates.
- Emit the existing `custom_rooms_json` object shape:
  - `rooms`
  - `stylegrounds`
- Feed that result into `generate_starter_map(..., custom_rooms_json=..., auto_connect_adjacent=True)`.

## Compatibility with the current workflow

You already have three pieces worth preserving:

1. Weighted template selection
The current `weight`, `difficulty`, `tags`, `hazard_chars`, and `max_hazard_density` logic still applies. It just needs to score placements in a graph instead of a single array.

2. Visual decoration
The existing styleground, decal, and helper-entity decoration logic can still be used as the last-mile renderer for instantiated room nodes.

3. Output format
The graph solver should still emit the same custom room JSON shape consumed by the current starter-map generator.

## What is new compared to `pcg_room_pool.schema.json`

The current schema only knows about a linear sequence of archetypes. The new graph schema adds:

- explicit abilities and items
- reusable lock definitions
- zone-level structure
- room exits as first-class data
- beat placement and solver-relevant rewards
- progression validation rules
- room budget and branch budget targets

## Recommended implementation plan

### Step 1: add a new generator, do not overload the current one

Create a new script rather than stretching the current weighted script too far:

- `generate_metroidvania_graph.py`

That keeps the linear pipeline stable while the graph solver matures.

### Step 2: reuse existing helpers

Lift these helpers from `generate_weighted_room_sequence.py` into shared utilities when you start implementing:

- `_hazard_density`
- `_layout_dimensions`
- `_ensure_spawn`
- `_room_style`
- `_room_visual_spec`
- `_build_map_stylegrounds`

### Step 3: define three intermediate data structures

The generator will be easier to reason about if it separates these models:

- `TemplateDef`: parsed static room template data
- `GraphNode`: abstract beat or transit node before room assignment
- `PlacedRoom`: final instantiated room with coordinates, layout, visuals, and links

### Step 4: emit a solver report

Mirror the current sequence report, but include graph-specific data:

- beat order actually reached
- solver inventory timeline
- locks opened and when
- unreachable optional rewards
- path from start to goal
- any rejected candidate placements and why

## Practical limits for Celeste

Celeste rooms do not natively behave like a fully dynamic metroidvania runtime. That means this workflow should stay honest about what is static and what is simulated.

Good fit:

- room graph planning
- ability-gated route structure
- item and checkpoint placement
- one-way shortcuts and revisits
- editor-time preview and validation

Needs mod-side implementation if you want the runtime to enforce it:

- actual item pickups that grant new traversal mechanics
- lock state persistence across room revisits
- world-state flags that alter rooms after a boss or switch

## Suggested next coding task

The next concrete step is to implement a read-only prototype that:

1. loads `metroidvania_graph.example.json`
2. builds an abstract beat graph
3. assigns room templates without exporting a `.bin` yet
4. writes a JSON solver report and an HTML debug view

That keeps risk low and makes the failure modes visible before you wire it into map emission.
