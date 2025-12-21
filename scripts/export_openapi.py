"""Export FastAPI OpenAPI schema to a file.

Usage:
  python scripts/export_openapi.py --out openapi.json

This script imports the FastAPI app from bot.api.app and writes the OpenAPI schema.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot.api.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Export OpenAPI schema")
    parser.add_argument("--out", default="openapi.json", help="Output file path")
    parser.add_argument(
        "--indent", type=int, default=2, help="JSON indentation (default: 2)"
    )
    args = parser.parse_args()

    app = create_app()
    schema = app.openapi()

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=args.indent) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
