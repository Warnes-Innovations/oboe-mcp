"""
OBO Session business logic — ported from obo_helper.py.

All public functions operate on Path objects or string paths.
session_file parameters accept an absolute path or a filename
relative to {base_dir}/.github/obo_sessions/.
"""

import json
import re
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCORE_COMPONENTS = {"urgency", "importance", "effort", "dependencies"}
_SESSION_RE = re.compile(r"^session_\d{8}_\d{6}\.json$")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def obo_sessions_dir(base_dir: str | Path) -> Path:
    """Return the .github/obo_sessions directory for a given base dir."""
    return Path(base_dir).resolve() / ".github" / "obo_sessions"


def resolve_session_file(session_file: str | Path, base_dir: str | Path | None = None) -> Path:
    """Resolve session_file to an absolute Path.

    Accepts:
    - An absolute path (returned as-is after resolving)
    - A bare filename → resolved relative to base_dir/.github/obo_sessions/
    """
    p = Path(session_file)
    if p.is_absolute():
        return p.resolve()
    if base_dir is not None:
        return (obo_sessions_dir(base_dir) / p).resolve()
    # Caller must pass an absolute path if base_dir is None
    raise ValueError(
        f"session_file '{session_file}' is relative but no base_dir was provided"
    )


# ---------------------------------------------------------------------------
# Low-level I/O
# ---------------------------------------------------------------------------

def load_session(session_file: Path) -> dict:
    with open(session_file, "r") as f:
        return json.load(f)


def save_session(session_file: Path, session: dict) -> None:
    with open(session_file, "w") as f:
        json.dump(session, f, indent=2)


# ---------------------------------------------------------------------------
# Priority score
# ---------------------------------------------------------------------------

def _recalc_priority(item: dict) -> int:
    """Recalculate priority_score from component fields in place."""
    item["priority_score"] = (
        item.get("urgency", 3)
        + item.get("importance", 3)
        + (6 - item.get("effort", 3))
        + item.get("dependencies", 1)
    )
    return item["priority_score"]


def _normalize_item(item: dict, idx: int) -> dict:
    """Apply defaults to a new item and calculate priority_score."""
    item.setdefault("id", idx)
    item.setdefault("status", "pending")
    item.setdefault("title", f"Item {item['id']}")
    item.setdefault("category", "General")
    item.setdefault("description", "")
    item.setdefault("urgency", 3)
    item.setdefault("importance", 3)
    item.setdefault("effort", 3)
    item.setdefault("dependencies", 1)
    item.setdefault("resolution", None)
    item.setdefault("skip_reason", None)
    # Always compute so it matches actual components
    _recalc_priority(item)
    return item


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

def _index_path(sessions_dir: Path) -> Path:
    return sessions_dir / "index.json"


def _is_valid_index(index: object) -> bool:
    """Return True if *index* has the expected top-level structure."""
    return (
        isinstance(index, dict)
        and index.get("format_version") == 1
        and isinstance(index.get("sessions"), list)
    )


def load_index(sessions_dir: Path) -> dict:
    idx_path = _index_path(sessions_dir)
    if idx_path.exists():
        with open(idx_path) as f:
            return json.load(f)
    return {"format_version": 1, "last_updated": "", "sessions": []}


def _save_index(sessions_dir: Path, index: dict) -> None:
    index["last_updated"] = datetime.now().isoformat()
    with open(_index_path(sessions_dir), "w") as f:
        json.dump(index, f, indent=2)


def _pending_count(session: dict) -> int:
    return len([i for i in session.get("items", []) if i.get("status") == "pending"])


def _rebuild_index_from_files(sessions_dir: Path) -> dict:
    """Scan all session_*.json files and return a fresh index dict (not saved)."""
    rows = []
    for sf in sorted(sessions_dir.glob("session_*.json")):
        try:
            s = load_session(sf)
            rows.append({
                "file": sf.name,
                "title": s.get("title", sf.stem),
                "status": s.get("status", "active"),
                "pending": _pending_count(s),
                "created": s.get("created", "")[:10],
            })
        except Exception:
            rows.append({
                "file": sf.name,
                "title": "",
                "status": "unreadable",
                "pending": 0,
                "created": "",
            })
    return {"format_version": 1, "last_updated": "", "sessions": rows}


def _upsert_index(sessions_dir: Path, session: dict, session_filename: str) -> None:
    """Add or update the index.json entry for this session.

    Automatically repairs a missing, corrupt, or structurally invalid index by
    rebuilding it from the session files on disk before applying the update.
    """
    try:
        index = load_index(sessions_dir)
        if not _is_valid_index(index):
            raise ValueError("Invalid index structure")
    except (json.JSONDecodeError, ValueError):
        index = _rebuild_index_from_files(sessions_dir)

    entry = {
        "file": session_filename,
        "title": session.get("title", session_filename),
        "status": session.get("status", "active"),
        "pending": _pending_count(session),
        "created": session.get("created", "")[:10],
    }
    for i, s in enumerate(index["sessions"]):
        if s["file"] == session_filename:
            index["sessions"][i] = entry
            _save_index(sessions_dir, index)
            return
    index["sessions"].append(entry)
    _save_index(sessions_dir, index)


# ---------------------------------------------------------------------------
# Public session operations
# ---------------------------------------------------------------------------

def create_session(
    session_file: Path,
    items: list[dict],
    title: str = "",
    description: str = "",
) -> dict:
    """Create a new session file and update index.json atomically.

    Raises FileExistsError if the session file already exists.
    """
    if session_file.exists():
        raise FileExistsError(f"Session file already exists: {session_file}")

    session_file.parent.mkdir(parents=True, exist_ok=True)

    normalized = [_normalize_item(dict(item), idx) for idx, item in enumerate(items, start=1)]

    session = {
        "session_file": session_file.name,
        "created": datetime.now().isoformat(),
        "title": title or session_file.stem,
        "description": description,
        "status": "active",
        "items": normalized,
    }

    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return session


def list_sessions(sessions_dir: Path, status_filter: str | None = None) -> list[dict]:
    """Return session summary dicts from index.json (fast path).

    Falls back to scanning session_*.json files if index.json is absent,
    corrupt, or structurally invalid, then rebuilds index.json.

    status_filter: 'active' | 'completed' | 'incomplete' | None
    """
    sessions_dir = Path(sessions_dir)
    idx_path = _index_path(sessions_dir)

    rows = None  # None signals that a rebuild is needed
    if idx_path.exists():
        try:
            index = load_index(sessions_dir)
            if _is_valid_index(index):
                rows = index["sessions"]
        except (json.JSONDecodeError, ValueError):
            rows = None  # corrupt index – fall through to rebuild

    if rows is None:
        # Slow path: scan files, rebuild index
        rebuilt = _rebuild_index_from_files(sessions_dir)
        rows = rebuilt["sessions"]
        if rows:
            _save_index(sessions_dir, rebuilt)

    # Apply status filter
    if status_filter == "active":
        rows = [r for r in rows if r.get("status") == "active"]
    elif status_filter == "completed":
        rows = [r for r in rows if r.get("status") == "completed"]
    elif status_filter == "incomplete":
        rows = [r for r in rows if r.get("status") == "active" and r.get("pending", 0) > 0]

    return rows


def session_status(session_file: Path) -> dict:
    """Return summary statistics for the session."""
    session = load_session(session_file)
    items = session.get("items", [])
    total = len(items)
    completed = len([i for i in items if i.get("status") == "completed"])
    skipped = len([i for i in items if i.get("status") == "skipped"])
    in_progress = len([i for i in items if i.get("status") == "in_progress"])
    pending = len([i for i in items if i.get("status") == "pending"])
    done = completed + skipped
    pct = (100 * done // total) if total > 0 else 0

    categories: dict[str, dict] = {}
    for item in items:
        cat = item.get("category", "General")
        categories.setdefault(cat, {"total": 0, "completed": 0})
        categories[cat]["total"] += 1
        if item.get("status") == "completed":
            categories[cat]["completed"] += 1

    return {
        "session_file": session_file.name,
        "title": session.get("title", ""),
        "status": session.get("status", "active"),
        "total": total,
        "completed": completed,
        "skipped": skipped,
        "in_progress": in_progress,
        "pending": pending,
        "done": done,
        "pct_done": pct,
        "categories": categories,
    }


def get_next(session_file: Path) -> dict | None:
    """Return the next item to work on.

    Prefers in_progress items (highest priority_score, then lowest id).
    Falls back to highest-priority pending item.
    Returns None if no actionable items remain.
    """
    session = load_session(session_file)
    items = session.get("items", [])

    in_progress = [i for i in items if i.get("status") == "in_progress"]
    pending = [i for i in items if i.get("status") == "pending"]

    if in_progress:
        return sorted(in_progress, key=lambda x: (-x.get("priority_score", 0), x["id"]))[0]
    if pending:
        return sorted(pending, key=lambda x: (-x.get("priority_score", 0), x["id"]))[0]
    return None


def list_items(session_file: Path, status_filter: str | None = None) -> list[dict]:
    """Return all items sorted by priority_score desc, optionally filtered."""
    session = load_session(session_file)
    items = session.get("items", [])
    if status_filter:
        items = [i for i in items if i.get("status") == status_filter]
    return sorted(items, key=lambda x: (-x.get("priority_score", 0), x.get("id", 0)))


def get_item(session_file: Path, item_id: str | int) -> dict | None:
    """Return full detail for a single item, or None if not found."""
    session = load_session(session_file)
    for item in session.get("items", []):
        if str(item.get("id")) == str(item_id):
            return item
    return None


def mark_complete(session_file: Path, item_id: str | int, resolution: str) -> dict:
    """Mark an item completed with resolution text. Returns updated session."""
    session = load_session(session_file)
    for item in session["items"]:
        if str(item["id"]) == str(item_id):
            item["status"] = "completed"
            item["resolution"] = resolution
            save_session(session_file, session)
            _upsert_index(session_file.parent, session, session_file.name)
            return session
    raise KeyError(f"Item {item_id} not found")


def mark_skip(session_file: Path, item_id: str | int, reason: str = "") -> dict:
    """Mark an item skipped. Returns updated session."""
    session = load_session(session_file)
    for item in session["items"]:
        if str(item["id"]) == str(item_id):
            item["status"] = "skipped"
            if reason:
                item["skip_reason"] = reason
            save_session(session_file, session)
            _upsert_index(session_file.parent, session, session_file.name)
            return session
    raise KeyError(f"Item {item_id} not found")


def update_field(
    session_file: Path, item_id: str | int, field: str, value: object
) -> dict:
    """Update a field on an item, auto-recalculating priority_score if needed.

    Returns the updated item dict.
    """
    session = load_session(session_file)
    for item in session["items"]:
        if str(item["id"]) == str(item_id):
            if field in _SCORE_COMPONENTS or field == "priority_score":
                value = int(value)
            item[field] = value
            if field in _SCORE_COMPONENTS:
                _recalc_priority(item)
            save_session(session_file, session)
            return item
    raise KeyError(f"Item {item_id} not found")
