#!/usr/bin/env python3
"""Generate weighted custom rooms, build a .bin map, and open Loenn MCP HTML preview."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import webbrowser
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_WORKSPACE = _HERE.parent.resolve()
os.environ.setdefault("LOENN_MCP_WORKSPACE", str(_WORKSPACE))

sys.path.insert(0, str(_HERE))


def _import_server():
    try:
        from loenn_mcp import server
        return server
    except ImportError:
        import importlib
        return importlib.import_module("server")


def _import_generator():
    import importlib
    return importlib.import_module("generate_weighted_room_sequence")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate weighted custom rooms, build a .bin map, and open HTML preview."
    )
    parser.add_argument("map_bin", help="Output .bin map path")
    parser.add_argument("room_pool_json", help="Path to weighted room pool JSON")
    parser.add_argument("room_count", nargs="?", type=int, default=7, help="Number of rooms to generate")
    parser.add_argument("seed", nargs="?", default="", help="Optional random seed")
    parser.add_argument("package", nargs="?", default="", help="Optional map package")
    parser.add_argument("room_prefix", nargs="?", default="", help="Optional room prefix")
    parser.add_argument("--required-tags", default="", help="Optional comma-separated required tag override")
    parser.add_argument("--min-tag-counts", default="", help="Optional JSON object for minimum tag counts")
    parser.add_argument(
        "--excluded-adjacent-tag-pairs",
        default="",
        help="Optional JSON array for excluded adjacency pairs",
    )
    parser.add_argument("--late-game-tags", default="", help="Optional comma-separated late-game tags")
    parser.add_argument(
        "--late-game-start-ratio",
        default="",
        help="Optional late-game start ratio override",
    )
    parser.add_argument("--report-out", default="", help="Optional path for JSON sequence report")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    map_path = Path(args.map_bin).resolve()
    pool_path = Path(args.room_pool_json).resolve()
    map_path.parent.mkdir(parents=True, exist_ok=True)
    seed = int(args.seed) if args.seed != "" else None

    if not pool_path.exists():
        print(f"Error: room pool file not found: {pool_path}", file=sys.stderr)
        sys.exit(1)

    generator = _import_generator()
    data = generator._load_pool(pool_path)
    meta = generator._apply_rule_overrides(data.get("meta", {}), args)
    max_hazard_density = float(meta.get("max_hazard_density", 0.16))
    rules = generator._parse_rules(meta)

    archetypes = generator._parse_archetypes(data, max_hazard_density=max_hazard_density)
    rng = generator.random.Random(seed)
    sequence = generator.generate_sequence(archetypes, room_count=args.room_count, rng=rng, rules=rules)
    custom_map = generator.build_custom_map(sequence, room_prefix=args.room_prefix, meta=meta)

    custom_rooms_json = json.dumps(custom_map, indent=2)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        tmp.write(custom_rooms_json)
        temp_json = Path(tmp.name)

    print(f"Generated weighted custom rooms: {temp_json}")

    server = _import_server()

    print(f"Generating weighted starter map: {map_path.name} ...")
    gen_result = server.generate_starter_map(
        str(map_path),
        template="minimal",
        package_name=args.package,
        room_prefix=args.room_prefix,
        custom_rooms_json=custom_rooms_json,
        auto_connect_adjacent=True,
        overwrite=True,
    )
    print(gen_result)

    if args.report_out:
        report_path = Path(args.report_out).resolve()
        report = generator._build_sequence_report(
            sequence,
            rules=rules,
            seed=seed,
            pool_path=pool_path,
            room_prefix=args.room_prefix,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote sequence report: {report_path}")

    out_dir = map_path.parent / "Temp"
    out_dir.mkdir(exist_ok=True)
    out_file = str(out_dir / f"map_preview_{map_path.stem}.html")

    print(f"Rendering preview: {map_path.name} ...")
    render_result = server.render_map_html(str(map_path), output_file=out_file)
    print(render_result)

    html_uri = Path(out_file).as_uri()
    print(f"Opening: {html_uri}")
    webbrowser.open(html_uri)


if __name__ == "__main__":
    main()
