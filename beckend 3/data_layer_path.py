"""Resolve the existing FinBuddy data-layer package for supported layouts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def _is_data_layer(path: Path) -> bool:
    """Return whether *path* contains the existing FinBuddy db package."""
    return (
        path.is_dir()
        and (path / "db" / "__init__.py").is_file()
        and (path / "db" / "database.py").is_file()
    )


def resolve_data_layer_dir(
    backend_file: str | Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Find the existing data layer without creating or replacing any files.

    Supported layouts place ``finbuddy.ui`` either beside the backend folder or
    inside a sibling ``fin-buddy-main`` project folder. An explicit environment
    override is authoritative and must point to a valid data-layer directory.
    """
    env = os.environ if environ is None else environ
    backend_dir = Path(backend_file).resolve().parent
    project_root = backend_dir.parent

    configured = env.get("FINBUDDY_DATA_LAYER_DIR", "").strip()
    if configured:
        selected = Path(configured).expanduser().resolve()
        if _is_data_layer(selected):
            return selected
        raise FileNotFoundError(
            "FINBUDDY_DATA_LAYER_DIR does not contain the existing FinBuddy "
            "data layer (expected db/__init__.py and db/database.py): "
            f"{selected}. Set FINBUDDY_DATA_LAYER_DIR to the directory that "
            "contains the db package."
        )

    candidates = (
        project_root / "finbuddy.ui" / "finbuddy",
        project_root / "fin-buddy-main" / "finbuddy.ui" / "finbuddy",
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if _is_data_layer(resolved):
            return resolved

    locations = ", ".join(str(path.resolve()) for path in candidates)
    raise FileNotFoundError(
        "The existing FinBuddy data layer was not found. Expected a directory "
        "containing db/__init__.py and db/database.py in one of these locations: "
        f"{locations}. Set FINBUDDY_DATA_LAYER_DIR to the existing data-layer "
        "directory. The backend will not create a replacement database."
    )
