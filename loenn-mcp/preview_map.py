#!/usr/bin/env python3
"""One-click Celeste .bin map preview.

Generates an interactive HTML map preview and opens it in the default browser.

Usage:
    python preview_map.py <path/to/map.bin>
    python preview_map.py <path/to/map.bin> [room-prefix]

VS Code task: the "Preview .bin Map" task in .vscode/tasks.json calls this
automatically on the currently active file (Ctrl+Shift+B or Run Task menu).
"""

import os
import sys
import webbrowser
from pathlib import Path

# ── locate workspace root (MaggyHelper/) and points server.py to it ──────────
_HERE      = Path(__file__).parent.resolve()
_WORKSPACE = _HERE.parent.resolve()
os.environ.setdefault("LOENN_MCP_WORKSPACE", str(_WORKSPACE))

# celeste_bin and server must be found in this directory
sys.path.insert(0, str(_HERE))


def _import_server():
    """Import server after env is fully configured."""
    try:
        from loenn_mcp import server          # installed package
        return server
    except ImportError:
        import importlib
        return importlib.import_module("server")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python preview_map.py <map.bin> [prefix]", file=sys.stderr)
        sys.exit(1)

    bin_arg = sys.argv[1]
    prefix  = sys.argv[2] if len(sys.argv) > 2 else ""

    bin_path = Path(bin_arg).resolve()

    if not bin_path.exists():
        print(f"Error: file not found: {bin_path}", file=sys.stderr)
        sys.exit(1)

    if bin_path.suffix.lower() != ".bin":
        print(f"Error: expected a .bin file, got: {bin_path.name}", file=sys.stderr)
        sys.exit(1)

    # Output HTML goes into a Temp/ folder next to the .bin file.
    # This works correctly whether running inside a mod or as a standalone tool.
    out_dir = bin_path.parent / "Temp"
    out_dir.mkdir(exist_ok=True)
    out_file = str(out_dir / f"map_preview_{bin_path.stem}.html")

    # Import server (deferred so env vars are set first)
    server = _import_server()

    print(f"Rendering: {bin_path.name} …")
    result = server.render_map_html(
        str(bin_path),
        prefix=prefix,
        output_file=out_file,
    )
    print(result)

    # Open in the default browser
    html_uri = Path(out_file).as_uri()
    print(f"Opening: {html_uri}")
    webbrowser.open(html_uri)


if __name__ == "__main__":
    main()
