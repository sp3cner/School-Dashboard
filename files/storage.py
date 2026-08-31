"""
Local persistence for the dashboard.

Everything is written as JSON into a ``data/`` folder next to this file
(gitignored). No credentials are stored — only fetched Canvas data, parsed
syllabus rows, a small ``meta`` record (last sync time, Canvas URL), and your
manual "turned in" overrides. Delete the folder (or use the sidebar button)
to start clean.
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

# DataFrame-backed stores and the plain-JSON stores.
_DF_STORES = ("canvas_assignments", "canvas_files", "syllabus_items")


def _path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(exist_ok=True)


def save_df(name: str, df: pd.DataFrame) -> None:
    _ensure_dir()
    _path(name).write_text(df.to_json(orient="records", date_format="iso"))


def load_df(name: str) -> pd.DataFrame:
    path = _path(name)
    if not path.exists():
        return pd.DataFrame()
    try:
        # convert_dates=False keeps ISO date strings as strings, so the app's
        # own tz-handling in the timeline stays in charge.
        return pd.read_json(io.StringIO(path.read_text()), convert_dates=False)
    except ValueError:
        return pd.DataFrame()


def save_json(name: str, obj) -> None:
    _ensure_dir()
    _path(name).write_text(json.dumps(obj, indent=2, default=str))


def load_json(name: str, default):
    path = _path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except ValueError:
        return default


def touch_meta(**fields) -> dict:
    """Merge ``fields`` into the meta record and stamp ``updated_at``."""
    meta = load_json("meta", {})
    meta.update(fields)
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_json("meta", meta)
    return meta


def clear_all() -> None:
    if DATA_DIR.exists():
        for f in DATA_DIR.glob("*.json"):
            f.unlink()


def has_saved_data() -> bool:
    return any(_path(n).exists() for n in _DF_STORES)
