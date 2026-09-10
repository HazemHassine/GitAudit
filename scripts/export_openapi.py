"""Export the FastAPI OpenAPI schema deterministically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maintainer_api.main import app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = Path(__file__).resolve().parent.parent / "docs/openapi.json"
    rendered = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not output.is_file() or output.read_text() != rendered:
            raise SystemExit("docs/openapi.json is out of date; run scripts/export_openapi.py")
        return
    output.write_text(rendered)


if __name__ == "__main__":
    main()
