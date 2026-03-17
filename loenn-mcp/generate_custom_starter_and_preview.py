#!/usr/bin/env python3
"""Generate a custom-layout .bin map and open Loenn MCP HTML preview."""

import os
import sys
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


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: python generate_custom_starter_and_preview.py <map.bin> <custom_rooms.json> [package] [room_prefix]",
            file=sys.stderr,
        )
        sys.exit(1)

    map_arg = sys.argv[1]
    custom_file_arg = sys.argv[2]
    package_name = sys.argv[3] if len(sys.argv) > 3 else ""
    room_prefix = sys.argv[4] if len(sys.argv) > 4 else ""

    map_path = Path(map_arg).resolve()
    custom_file = Path(custom_file_arg).resolve()

    if not custom_file.exists():
        print(f"Error: custom rooms file not found: {custom_file}", file=sys.stderr)
        sys.exit(1)

    custom_rooms_json = custom_file.read_text(encoding="utf-8")
    map_path.parent.mkdir(parents=True, exist_ok=True)

    server = _import_server()

    print(f"Generating custom starter map: {map_path.name} from {custom_file.name} ...")
    gen_result = server.generate_starter_map(
        str(map_path),
        template="minimal",
        package_name=package_name,
        room_prefix=room_prefix,
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
