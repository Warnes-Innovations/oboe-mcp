# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
OBO Session business logic — ported from obo_helper.py.

All public functions operate on Path objects or string paths.
session_file parameters accept an absolute path or a filename
relative to {base_dir}/.github/obo_sessions/.
"""

import json
import re
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ACTIONABLE_STATUSES = {"pending", "in_progress"}
_DEFERRED_STATUSES = {"deferred"}
_BLOCKED_STATUSES = {"blocked"}
_TERMINAL_STATUSES = {"completed", "skipped"}
_OPEN_ITEM_STATUSES = (
    _ACTIONABLE_STATUSES | _DEFERRED_STATUSES | _BLOCKED_STATUSES
)
_VALID_ITEM_STATUSES = _OPEN_ITEM_STATUSES | _TERMINAL_STATUSES
_VALID_APPROVAL_STATUSES = {"unreviewed", "approved", "denied"}
_VALID_APPROVAL_MODES = {"immediate", "delayed"}
_SCORE_COMPONENTS = {"urgency", "importance", "effort", "dependencies"}
_SESSION_RE = re.compile(r"^session_\d{8}_\d{6}\.json$")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def obo_sessions_dir(base_dir: str | Path) -> Path:
    """Return the .github/obo_sessions directory for a given base dir."""
    return Path(base_dir).resolve() / ".github" / "obo_sessions"


def resolve_base_dir(base_dir: str | Path | None = None) -> Path:
    """Resolve the project base directory for CLI use.

    Priority:
      1. *base_dir* if supplied (converted to an absolute path)
      2. CWD if it contains ``.github/obo_sessions/``
      3. CWD as a fallback (directory may not yet exist)
    """
    if base_dir is not None:
        return Path(base_dir).resolve()
    cwd = Path.cwd()
    if (cwd / ".github" / "obo_sessions").exists():
        return cwd
    return cwd


def validate_session_filename(session_filename: str) -> str:
    """Validate the documented session filename convention."""
    if not _SESSION_RE.fullmatch(session_filename):
        raise ValueError(
            "Invalid session filename. Expected format: "
            "session_YYYYMMDD_HHMMSS.json"
        )
    return session_filename


def resolve_session_file(
    session_file: str | Path,
    base_dir: str | Path | None = None,
) -> Path:
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
        f"session_file '{session_file}' is relative but no base_dir "
        "was provided"
    )


# ---------------------------------------------------------------------------
# Low-level I/O
# ---------------------------------------------------------------------------

def load_session(session_file: Path) -> dict:
    with open(session_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(session_file: Path, session: dict) -> None:
    with open(session_file, "w", encoding="utf-8") as f:
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


def _validate_item_status(status: object) -> str:
    """Validate item status values used for workflow state transitions."""
    if not isinstance(status, str) or status not in _VALID_ITEM_STATUSES:
        raise ValueError(
            "Invalid item status. Expected one of: "
            f"{sorted(_VALID_ITEM_STATUSES)}"
        )
    return status


def _validate_approval_status(status: object) -> str:
    """Validate approval metadata stored on an item."""
    if (
        not isinstance(status, str)
        or status not in _VALID_APPROVAL_STATUSES
    ):
        raise ValueError(
            "Invalid approval status. Expected one of: "
            f"{sorted(_VALID_APPROVAL_STATUSES)}"
        )
    return status


def _validate_approval_mode(mode: object) -> str | None:
    """Validate the optional approval timing mode stored on an item."""
    if mode is None:
        return None
    if not isinstance(mode, str) or mode not in _VALID_APPROVAL_MODES:
        raise ValueError(
            "Invalid approval mode. Expected one of: "
            f"{sorted(_VALID_APPROVAL_MODES)}"
        )
    return mode


def _normalize_approval_fields(item: dict) -> None:
    """Apply defaults and validation for item approval metadata."""
    item.setdefault("approval_status", "unreviewed")
    item.setdefault("approval_mode", None)
    item.setdefault("approved_at", None)
    item.setdefault("approval_note", None)

    item["approval_status"] = _validate_approval_status(
        item["approval_status"]
    )
    item["approval_mode"] = _validate_approval_mode(item["approval_mode"])

    if item["approval_status"] != "approved":
        item["approval_mode"] = None
        item["approved_at"] = None


def _normalize_item(item: dict, idx: int) -> dict:
    """Apply defaults to a new item and calculate priority_score."""
    item.setdefault("id", idx)
    item.setdefault("status", "pending")
    _validate_item_status(item["status"])
    item.setdefault("title", f"Item {item['id']}")
    item.setdefault("category", "General")
    item.setdefault("description", "")
    item.setdefault("urgency", 3)
    item.setdefault("importance", 3)
    item.setdefault("effort", 3)
    item.setdefault("dependencies", 1)
    item.setdefault("resolution", None)
    item.setdefault("skip_reason", None)
    item.setdefault("blocker", None)
    item.setdefault("blocked_at", None)
    _normalize_approval_fields(item)
    # Always compute so it matches actual components
    _recalc_priority(item)
    return item


def _normalize_existing_items(session: dict) -> None:
    """Backfill any newer item fields when loading older session files."""
    normalized = []
    for idx, item in enumerate(session.get("items", []), start=1):
        normalized.append(_normalize_item(dict(item), item.get("id", idx)))
    session["items"] = normalized


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
        with open(idx_path, encoding="utf-8") as f:
            return json.load(f)
    return {"format_version": 1, "last_updated": "", "sessions": []}


def _save_index(sessions_dir: Path, index: dict) -> None:
    index["last_updated"] = datetime.now().isoformat()
    with open(_index_path(sessions_dir), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def _pending_count(session: dict) -> int:
    return len(
        [i for i in session.get("items", []) if i.get("status") == "pending"]
    )


def _in_progress_count(session: dict) -> int:
    return len(
        [
            i for i in session.get("items", [])
            if i.get("status") == "in_progress"
        ]
    )


def _actionable_count(session: dict) -> int:
    return len(
        [
            i for i in session.get("items", [])
            if i.get("status") in _ACTIONABLE_STATUSES
        ]
    )


def _blocked_count(session: dict) -> int:
    return len(
        [
            i for i in session.get("items", [])
            if i.get("status") in _BLOCKED_STATUSES
        ]
    )


def _deferred_count(session: dict) -> int:
    return len(
        [
            i for i in session.get("items", [])
            if i.get("status") in _DEFERRED_STATUSES
        ]
    )


def _approval_count(session: dict, approval_status: str) -> int:
    return len(
        [
            item
            for item in session.get("items", [])
            if item.get("approval_status", "unreviewed") == approval_status
        ]
    )


def _open_count(session: dict) -> int:
    return len(
        [
            i for i in session.get("items", [])
            if i.get("status") in _OPEN_ITEM_STATUSES
        ]
    )


def _sync_session_status(session: dict) -> str:
    """Keep the session-level status in sync with item states."""
    if session.get("active_child_session"):
        session["status"] = "paused"
        session.pop("completed_at", None)
    elif _open_count(session) > 0:
        session["status"] = "active"
        session.pop("completed_at", None)
    else:
        session["status"] = "completed"
        session.setdefault("completed_at", datetime.now().isoformat())
    return session["status"]


def _rebuild_index_from_files(sessions_dir: Path) -> dict:
    """Scan all session_*.json files and return a fresh index dict."""
    rows = []
    for sf in sorted(sessions_dir.glob("session_*.json")):
        try:
            s = load_session(sf)
            rows.append({
                "file": sf.name,
                "title": s.get("title", sf.stem),
                "status": s.get("status", "active"),
                "pending": _pending_count(s),
                "in_progress": _in_progress_count(s),
                "deferred": _deferred_count(s),
                "blocked": _blocked_count(s),
                "actionable": _actionable_count(s),
                "open": _open_count(s),
                "created": s.get("created", "")[:10],
                "parent_session_file": s.get("parent_session_file"),
                "active_child_session": s.get("active_child_session"),
            })
        except (OSError, ValueError, json.JSONDecodeError):
            rows.append({
                "file": sf.name,
                "title": "",
                "status": "unreadable",
                "pending": 0,
                "in_progress": 0,
                "deferred": 0,
                "blocked": 0,
                "actionable": 0,
                "open": 0,
                "created": "",
                "parent_session_file": None,
                "active_child_session": None,
            })
    return {"format_version": 1, "last_updated": "", "sessions": rows}


def _upsert_index(
    sessions_dir: Path,
    session: dict,
    session_filename: str,
) -> None:
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
        "in_progress": _in_progress_count(session),
        "deferred": _deferred_count(session),
        "blocked": _blocked_count(session),
        "actionable": _actionable_count(session),
        "open": _open_count(session),
        "created": session.get("created", "")[:10],
        "parent_session_file": session.get("parent_session_file"),
        "active_child_session": session.get("active_child_session"),
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
    parent_session_file: str | None = None,
    parent_item_id: str | int | None = None,
) -> dict:
    """Create a new session file and update index.json atomically.

    Raises FileExistsError if the session file already exists.
    """
    validate_session_filename(session_file.name)

    if session_file.exists():
        raise FileExistsError(f"Session file already exists: {session_file}")

    session_file.parent.mkdir(parents=True, exist_ok=True)

    normalized = [
        _normalize_item(dict(item), idx)
        for idx, item in enumerate(items, start=1)
    ]

    session = {
        "session_file": session_file.name,
        "created": datetime.now().isoformat(),
        "title": title or session_file.stem,
        "description": description,
        "status": "active",
        "parent_session_file": parent_session_file,
        "parent_item_id": parent_item_id,
        "child_session_files": [],
        "active_child_session": None,
        "items": normalized,
    }

    _sync_session_status(session)
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return session


def list_sessions(
    sessions_dir: Path,
    status_filter: str | None = None,
) -> list[dict]:
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
    elif status_filter == "paused":
        rows = [r for r in rows if r.get("status") == "paused"]
    elif status_filter == "completed":
        rows = [r for r in rows if r.get("status") == "completed"]
    elif status_filter == "incomplete":
        rows = [
            r for r in rows
            if r.get("status") in {"active", "paused"}
            and r.get("open", r.get("actionable", r.get("pending", 0))) > 0
        ]

    return rows


def session_status(session_file: Path) -> dict:
    """Return summary statistics for the session."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    items = session.get("items", [])
    total = len(items)
    completed = len([i for i in items if i.get("status") == "completed"])
    skipped = len([i for i in items if i.get("status") == "skipped"])
    in_progress = len([i for i in items if i.get("status") == "in_progress"])
    pending = len([i for i in items if i.get("status") == "pending"])
    deferred = len([i for i in items if i.get("status") == "deferred"])
    blocked = len([i for i in items if i.get("status") == "blocked"])
    done = completed + skipped
    pct = (100 * done // total) if total > 0 else 0
    approval = {
        "unreviewed": _approval_count(session, "unreviewed"),
        "approved": _approval_count(session, "approved"),
        "denied": _approval_count(session, "denied"),
    }

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
        "deferred": deferred,
        "blocked": blocked,
        "open": pending + in_progress + deferred + blocked,
        "done": done,
        "pct_done": pct,
        "approval": approval,
        "categories": categories,
        "parent_session_file": session.get("parent_session_file"),
        "parent_item_id": session.get("parent_item_id"),
        "child_session_files": session.get("child_session_files", []),
        "active_child_session": session.get("active_child_session"),
    }


def get_next(session_file: Path) -> dict | None:
    """Return the next item to work on.

    Prefers in_progress items (highest priority_score, then lowest id).
    Falls back to highest-priority pending item, then deferred item.
    Returns None if no actionable items remain.
    """
    session = load_session(session_file)
    _normalize_existing_items(session)
    if (
        session.get("status") == "paused"
        and session.get("active_child_session")
    ):
        raise ValueError(
            "Session is paused by active child session: "
            f"{session['active_child_session']}"
        )
    items = session.get("items", [])

    in_progress = [i for i in items if i.get("status") == "in_progress"]
    pending = [i for i in items if i.get("status") == "pending"]
    deferred = [i for i in items if i.get("status") == "deferred"]

    if in_progress:
        return sorted(
            in_progress,
            key=lambda x: (-x.get("priority_score", 0), x["id"]),
        )[0]
    if pending:
        return sorted(
            pending,
            key=lambda x: (-x.get("priority_score", 0), x["id"]),
        )[0]
    if deferred:
        return sorted(
            deferred,
            key=lambda x: (-x.get("priority_score", 0), x["id"]),
        )[0]
    return None


def list_items(
    session_file: Path,
    status_filter: str | None = None,
) -> list[dict]:
    """Return all items sorted by priority_score desc, optionally filtered."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    items = session.get("items", [])
    if status_filter:
        items = [i for i in items if i.get("status") == status_filter]
    return sorted(
        items,
        key=lambda x: (-x.get("priority_score", 0), x.get("id", 0)),
    )


def get_item(session_file: Path, item_id: str | int) -> dict | None:
    """Return full detail for a single item, or None if not found."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    for item in session.get("items", []):
        if str(item.get("id")) == str(item_id):
            return item
    return None


def _require_item(session: dict, item_id: str | int) -> dict:
    for item in session.get("items", []):
        if str(item.get("id")) == str(item_id):
            return item
    raise KeyError(f"Item {item_id} not found")


def _clear_blocker_fields(item: dict) -> None:
    item["blocker"] = None
    item["blocked_at"] = None


def _blocker_payload(blocker: str | dict) -> dict:
    if isinstance(blocker, dict):
        return blocker
    return {"summary": blocker}


def mark_complete(
    session_file: Path,
    item_id: str | int,
    resolution: str,
) -> dict:
    """Mark an item completed with resolution text. Returns updated session."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    item = _require_item(session, item_id)
    item["status"] = "completed"
    item["resolution"] = resolution
    _clear_blocker_fields(item)
    _sync_session_status(session)
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return session


def mark_skip(
    session_file: Path,
    item_id: str | int,
    reason: str = "",
) -> dict:
    """Mark an item skipped. Returns updated session."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    item = _require_item(session, item_id)
    item["status"] = "skipped"
    if reason:
        item["skip_reason"] = reason
    _clear_blocker_fields(item)
    _sync_session_status(session)
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return session


def mark_blocked(
    session_file: Path,
    item_id: str | int,
    blocker: str | dict,
) -> dict:
    """Mark an item blocked and store blocker metadata."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    item = _require_item(session, item_id)
    item["status"] = "blocked"
    item["blocker"] = _blocker_payload(blocker)
    item["blocked_at"] = datetime.now().isoformat()
    _sync_session_status(session)
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return session


def mark_in_progress(session_file: Path, item_id: str | int) -> dict:
    """Mark an item in progress. Returns updated session."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    item = _require_item(session, item_id)
    item["status"] = "in_progress"
    _clear_blocker_fields(item)
    _sync_session_status(session)
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return session


def complete_session(session_file: Path) -> dict:
    """Mark the session completed when no actionable items remain."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    if _open_count(session) > 0:
        raise ValueError(
            "Cannot complete session while pending, in_progress, "
            "deferred, or blocked "
            "items remain"
        )
    session["status"] = "completed"
    session.setdefault("completed_at", datetime.now().isoformat())
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return session


def create_child_session(
    parent_session_file: Path,
    child_session_file: Path,
    items: list[dict],
    title: str = "",
    description: str = "",
    parent_item_id: str | int | None = None,
) -> dict:
    """Create a child session, pause the parent, and optionally block an item.
    """
    parent_session = load_session(parent_session_file)
    _normalize_existing_items(parent_session)
    if parent_session.get("status") == "completed":
        raise ValueError(
            "Cannot create a child session from a completed parent"
        )
    if parent_session.get("active_child_session"):
        raise ValueError(
            "Parent session already has an active child session: "
            f"{parent_session['active_child_session']}"
        )

    if parent_item_id is not None:
        _require_item(parent_session, parent_item_id)

    child_session = create_session(
        child_session_file,
        items,
        title=title,
        description=description,
        parent_session_file=parent_session_file.name,
        parent_item_id=parent_item_id,
    )

    parent_session.setdefault("child_session_files", [])
    if child_session_file.name not in parent_session["child_session_files"]:
        parent_session["child_session_files"].append(child_session_file.name)
    parent_session["active_child_session"] = child_session_file.name

    if parent_item_id is not None:
        parent_item = _require_item(parent_session, parent_item_id)
        parent_item["status"] = "blocked"
        parent_item["blocker"] = {
            "type": "child_session",
            "session_file": child_session_file.name,
            "title": child_session.get("title"),
            "summary": (
                "Parent work is blocked until child session "
                f"{child_session_file.name} is completed"
            ),
        }
        parent_item["blocked_at"] = datetime.now().isoformat()

    _sync_session_status(parent_session)
    save_session(parent_session_file, parent_session)
    _upsert_index(
        parent_session_file.parent,
        parent_session,
        parent_session_file.name,
    )

    return {
        "parent_session": parent_session,
        "child_session": child_session,
    }


def complete_child_session(
    child_session_file: Path,
    resolution: str = "",
) -> dict:
    """Complete a child session and resume its parent session."""
    child_session = complete_session(child_session_file)
    parent_session_name = child_session.get("parent_session_file")
    if not parent_session_name:
        raise ValueError("Session is not a child session")

    parent_session_file = child_session_file.parent / parent_session_name
    parent_session = load_session(parent_session_file)
    _normalize_existing_items(parent_session)
    if parent_session.get("active_child_session") == child_session_file.name:
        parent_session["active_child_session"] = None

    parent_item_id = child_session.get("parent_item_id")
    if parent_item_id is not None:
        parent_item = _require_item(parent_session, parent_item_id)
        blocker = parent_item.get("blocker") or {}
        if blocker.get("session_file") == child_session_file.name:
            parent_item["status"] = "pending"
            _clear_blocker_fields(parent_item)
            if resolution:
                parent_item["child_session_resolution"] = resolution

    _sync_session_status(parent_session)
    save_session(parent_session_file, parent_session)
    _upsert_index(
        parent_session_file.parent,
        parent_session,
        parent_session_file.name,
    )

    return {
        "child_session": child_session,
        "parent_session": parent_session,
    }


def merge_items(session_file: Path, items: list[dict]) -> dict:
    """Append items to an existing session and reactivate it if needed."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    existing_ids = {str(item.get("id")) for item in session.get("items", [])}
    numeric_ids = [
        int(item_id) for item_id in existing_ids if item_id.isdigit()
    ]
    next_idx = max(numeric_ids, default=0) + 1
    merged_items = []

    for raw_item in items:
        item = dict(raw_item)
        if "id" not in item:
            while str(next_idx) in existing_ids:
                next_idx += 1
            item["id"] = next_idx
            next_idx += 1
        if str(item["id"]) in existing_ids:
            raise ValueError(f"Duplicate item id: {item['id']}")
        normalized = _normalize_item(item, item["id"])
        session.setdefault("items", []).append(normalized)
        merged_items.append(normalized)
        existing_ids.add(str(normalized["id"]))

    _sync_session_status(session)
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return {
        "session": session,
        "merged_items": merged_items,
    }


def set_approval(
    session_file: Path,
    item_id: str | int,
    approval_status: str,
    approval_mode: str | None = None,
    note: str | None = None,
    lifecycle_status: str | None = None,
) -> dict:
    """Set approval metadata and optional lifecycle state on an item."""
    session = load_session(session_file)
    _normalize_existing_items(session)
    item = _require_item(session, item_id)

    if approval_mode in {"", "none", "null"}:
        approval_mode = None
    if note in {"", "none", "null"}:
        note = None
    if lifecycle_status in {"", "none", "null"}:
        lifecycle_status = None

    approval_status = _validate_approval_status(approval_status)
    approval_mode = _validate_approval_mode(approval_mode)
    if lifecycle_status is not None:
        lifecycle_status = _validate_item_status(lifecycle_status)

    if approval_status != "approved" and approval_mode is not None:
        raise ValueError(
            "approval_mode can only be set when approval_status is "
            "'approved'"
        )

    if approval_status == "approved":
        if approval_mode is None:
            approval_mode = "immediate"
        item["approval_status"] = approval_status
        item["approval_mode"] = approval_mode
        item["approved_at"] = (
            item.get("approved_at") or datetime.now().isoformat()
        )
    else:
        item["approval_status"] = approval_status
        item["approval_mode"] = None
        item["approved_at"] = None

    item["approval_note"] = note

    if lifecycle_status is not None:
        item["status"] = lifecycle_status
    elif approval_status == "approved" and approval_mode == "delayed":
        item["status"] = "deferred"

    if item["status"] != "blocked":
        _clear_blocker_fields(item)

    _sync_session_status(session)
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return item


def update_field(
    session_file: Path,
    item_id: str | int,
    field: str,
    value: str | int,
) -> dict:
    """Update a field on an item, auto-recalculating priority_score if needed.

    Returns the updated item dict.
    """
    session = load_session(session_file)
    _normalize_existing_items(session)
    item = _require_item(session, item_id)
    new_value: str | int | None = value
    if field == "status":
        new_value = _validate_item_status(new_value)
        if new_value != "blocked":
            _clear_blocker_fields(item)
    elif field == "approval_status":
        new_value = _validate_approval_status(new_value)
        if new_value == "approved":
            item["approved_at"] = (
                item.get("approved_at") or datetime.now().isoformat()
            )
        else:
            item["approval_mode"] = None
            item["approved_at"] = None
    elif field == "approval_mode":
        if new_value in {"", "none", "null"}:
            new_value = None
        new_value = _validate_approval_mode(new_value)
        if new_value is not None:
            item["approval_status"] = "approved"
            item["approved_at"] = (
                item.get("approved_at") or datetime.now().isoformat()
            )
    elif field in {
        "resolution",
        "skip_reason",
        "blocked_at",
        "approved_at",
        "approval_note",
    }:
        if new_value in {"", "none", "null"}:
            new_value = None
    if field in _SCORE_COMPONENTS or field == "priority_score":
        if new_value is None:
            raise ValueError(f"Field '{field}' cannot be null")
        new_value = int(new_value)
    item[field] = new_value
    if field in _SCORE_COMPONENTS:
        _recalc_priority(item)
    _sync_session_status(session)
    save_session(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)
    return item
