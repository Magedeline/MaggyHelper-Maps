#!/usr/bin/env python3
"""Generate a .bin map from a metroidvania graph spec and open HTML preview."""

from __future__ import annotations

import argparse
import importlib
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
        return importlib.import_module("server")


def _import_generator():
    return importlib.import_module("generate_metroidvania_graph")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate metroidvania graph rooms, build a .bin map, and open HTML preview."
    )
    parser.add_argument("map_bin", help="Output .bin map path")
    parser.add_argument("graph_spec_json", help="Path to metroidvania graph spec JSON")
    parser.add_argument("package", nargs="?", default="", help="Optional map package override")
    parser.add_argument("room_prefix", nargs="?", default="", help="Optional room prefix override")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed override")
    parser.add_argument("--report-out", default="", help="Optional solver report JSON path")
    parser.add_argument("--custom-json-out", default="", help="Optional generated custom room JSON path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    map_path = Path(args.map_bin).resolve()
    spec_path = Path(args.graph_spec_json).resolve()
    map_path.parent.mkdir(parents=True, exist_ok=True)

    if not spec_path.exists():
        print(f"Error: graph spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    generator = _import_generator()
    custom_map, report = generator.build_custom_map_from_spec_file(
        spec_path,
        seed=args.seed,
        room_prefix=args.room_prefix,
    )
    custom_rooms_json = json.dumps(custom_map, indent=2)

    if args.custom_json_out:
        custom_json_path = Path(args.custom_json_out).resolve()
        custom_json_path.parent.mkdir(parents=True, exist_ok=True)
        custom_json_path.write_text(custom_rooms_json, encoding="utf-8")
        print(f"Custom rooms: {custom_json_path}")
    else:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            tmp.write(custom_rooms_json)
            print(f"Generated custom rooms: {tmp.name}")

    if args.report_out:
        report_path = Path(args.report_out).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Solver report: {report_path}")

    server = _import_server()

    print(f"Generating metroidvania starter map: {map_path.name} ...")
    gen_result = server.generate_starter_map(
        str(map_path),
        template="minimal",
        package_name=args.package,
        room_prefix="",
        custom_rooms_json=custom_rooms_json,
        auto_connect_adjacent=True,
        overwrite=True,
    )
    print(gen_result)

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