"""Verify the built API wheel contains usable package metadata and source."""

from pathlib import Path
from zipfile import ZipFile

import tomllib


def main() -> None:
    """Check the current project version's wheel, failing on missing or corrupt files."""
    root = Path(__file__).resolve().parent.parent
    project = tomllib.loads((root / "apps/api/pyproject.toml").read_text())["project"]
    wheel = root / "dist" / f"{project['name'].replace('-', '_')}-{project['version']}-py3-none-any.whl"
    with ZipFile(wheel) as archive:
        if archive.testzip() is not None:
            raise ValueError("Wheel contains corrupt data")
        names = archive.namelist()
        if "maintainer_api/main.py" not in names:
            raise ValueError("Wheel is missing the application package")
        if not any(name.endswith(".dist-info/METADATA") for name in names):
            raise ValueError("Wheel is missing package metadata")
    print(f"Verified {wheel.name}")


if __name__ == "__main__":
    main()
