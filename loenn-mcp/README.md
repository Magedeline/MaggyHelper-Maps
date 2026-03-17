# loenn-mcp

Celeste map editor MCP server for AI agents.

This package provides tools for reading, editing, analyzing, and previewing Celeste .bin maps without requiring Loenn at runtime.

## Highlights

- Read and inspect maps and rooms
- Create maps and rooms, edit tiles, entities, and triggers
- Generate starter maps from built-in or custom JSON templates
- Auto-link touching rooms with TeleportTrigger pairs
- Render interactive HTML map previews

## Quick start

```bash
pip install loenn-mcp
```

Run as MCP stdio server:

```bash
python -m loenn_mcp.server
```

Set workspace root using environment variable:

```bash
LOENN_MCP_WORKSPACE=/path/to/mod python -m loenn_mcp.server
```

## Weighted room sequence workflow

This repository includes a lightweight procedural workflow that is easy to tune for Celeste-style map authoring.

Files:

- `pcg_room_pool.schema.json`: JSON schema for archetype pool files
- `pcg_room_pool.example.json`: editable starter pool (tags, weights, difficulty, layouts)
- `pcg_room_pool.movement_focus.json`: bundled movement-heavy preset with stronger dash/climb pacing
- `generate_weighted_room_sequence.py`: outputs custom room JSON
- `generate_weighted_and_preview.py`: generates a `.bin` map from weighted rooms and opens HTML preview
- `custom_rooms_example.json`: decorated custom-map example with entities, decals, and stylegrounds

Generate custom room JSON only:

```bash
python generate_weighted_room_sequence.py out_rooms.json --pool pcg_room_pool.example.json --rooms 7 --seed 42
```

Useful `meta` tuning knobs in the pool JSON:

- `room_style`: visual theme used for generated stylegrounds, room flags, decals, and helper entities
- `required_tags`: tags that must appear at least once
- `min_tag_counts`: minimum count per tag (example: `{ "hazard": 2 }`)
- `excluded_adjacent_tag_pairs`: prevent rough pacing transitions (example: `[["rest", "rest"]]`)
- `late_game_tags`: tags preferred in the final stretch
- `late_game_start_ratio`: where late-game preference begins (default `0.6`)

Those same rule knobs can be overridden from the command line without editing the pool file:

```bash
python generate_weighted_room_sequence.py out_rooms.json \
  --pool pcg_room_pool.movement_focus.json \
  --rooms 8 \
  --seed 42 \
  --required-tags checkpoint,climb \
  --min-tag-counts hazard=2,dash=3 \
  --excluded-adjacent-tag-pairs rest>rest,climb>climb \
  --late-game-tags hazard,finale,precision \
  --late-game-start-ratio 0.7 \
  --report-out out_sequence_report.json
```

The JSON report includes the chosen archetype order, per-room difficulty and tags, tag totals, and whether the constraint rules were satisfied.

`custom_rooms_json` now also accepts an object with this shape:

```json
{
  "stylegrounds": {
    "backgrounds": [{ "name": "parallax", "texture": "bgs/02/bg0" }],
    "foregrounds": []
  },
  "rooms": [
    {
      "name": "custom_start",
      "layout": "...",
      "entities": [{ "name": "booster", "x": 72, "y": 24 }],
      "fgdecals": [{ "texture": "maggy/generic/grass_a", "x": 96, "y": 40 }],
      "bgdecals": [{ "texture": "maggy/9_beyond_summit/cloud_a", "x": 56, "y": 8 }],
      "windPattern": "Left"
    }
  ]
}
```

Room entries remain backward-compatible with the old array format; the object form just adds map-level stylegrounds and richer per-room dressing.

## Metroidvania graph workflow design

This repository also includes a larger graph-first design for metroidvania-style generation. It is not wired into a generator yet, but it defines the input format and implementation shape for a gated, solver-validated workflow.

Files:

- `metroidvania_graph.schema.json`: schema for graph-first generation specs
- `metroidvania_graph.example.json`: example zone, beat, item, lock, and template config
- `METROIDVANIA_GRAPH_DESIGN.md`: implementation notes and integration plan
- `generate_metroidvania_graph.py`: solve a graph spec into `custom_rooms_json`
- `generate_metroidvania_and_preview.py`: solve a graph spec, generate a `.bin`, and open HTML preview

This workflow extends the current weighted pipeline rather than replacing it. The target output is still the existing `custom_rooms_json` object shape that `generate_starter_map` already accepts.

Generate custom room JSON from the example graph spec:

```bash
python generate_metroidvania_graph.py out_metroidvania_rooms.json --spec metroidvania_graph.example.json --seed 42 --report-out out_metroidvania_report.json
```

Generate `.bin` map + preview directly:

```bash
python generate_metroidvania_and_preview.py ../Maps/Maggy/LoennMcpMetroidvania.bin metroidvania_graph.example.json Maggy/LoennMcpMetroidvania mv_
```

Current limitations of the generator:

- beat order is taken from `graph.beats`
- progression is solved linearly, then emitted as a left-to-right room chain
- branch and loop budgets are not yet realized as true non-linear geometry

Generate `.bin` map + preview directly:

```bash
python generate_weighted_and_preview.py ../Maps/Maggy/LoennMcpWeightedStarter.bin pcg_room_pool.example.json 7 42 Maggy/LoennMcpWeightedStarter
```

In VS Code, the `Loenn MCP: Generate Weighted + Preview` task now lets you:

- pick between bundled weighted pool presets
- override pacing rules for a single run
- write a sequence report next to the generated preview assets
