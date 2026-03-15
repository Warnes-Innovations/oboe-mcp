"""
OBO MCP Server — 9 tools for One-By-One session management.

Uses FastMCP for concise tool registration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from obo_mcp.session import (
    create_session,
    get_item,
    get_next,
    list_items,
    list_sessions,
    mark_complete,
    mark_skip,
    obo_sessions_dir,
    resolve_session_file,
    session_status,
    update_field,
)

mcp = FastMCP("obo-mcp", instructions="One-By-One session management tools")


# ---------------------------------------------------------------------------
# Helper: resolve session_file argument
# ---------------------------------------------------------------------------

def _resolve(session_file: str, base_dir: str | None = None) -> Path:
    """Resolve session_file (absolute path or bare filename) to a Path."""
    p = Path(session_file)
    if p.is_absolute():
        return p
    if base_dir:
        return obo_sessions_dir(base_dir) / session_file
    raise ValueError(
        "session_file must be an absolute path or base_dir must be provided"
    )


# ---------------------------------------------------------------------------
# Tool: obo_create
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_create(
    base_dir: str,
    title: str,
    description: str,
    items: list[dict],
    session_filename: Optional[str] = None,
) -> str:
    """Create a new OBO session file and update index.json atomically.

    Args:
        base_dir: Project root directory (session goes in {base_dir}/.github/obo_sessions/)
        title: Human-readable session title
        description: What this session is reviewing
        items: List of item dicts (title, description, urgency, importance, effort, dependencies, category are all optional with defaults)
        session_filename: Optional explicit filename (e.g. session_20260314_120000.json).
                          If omitted, generated from current timestamp.
    """
    from datetime import datetime

    sessions_dir = obo_sessions_dir(base_dir)
    if session_filename:
        sf = sessions_dir / session_filename
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sf = sessions_dir / f"session_{ts}.json"

    try:
        session = create_session(sf, items, title=title, description=description)
    except FileExistsError as e:
        return f"ERROR: {e}"

    return json.dumps({
        "session_file": sf.name,
        "path": str(sf),
        "title": session["title"],
        "items_created": len(session["items"]),
        "status": "active",
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool: obo_list_sessions
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_list_sessions(
    base_dir: str,
    status_filter: Optional[str] = None,
) -> str:
    """List OBO sessions from index.json.

    Args:
        base_dir: Project root directory
        status_filter: Optional filter — 'active', 'completed', or 'incomplete'
                       (incomplete = active sessions with pending items)
    """
    sessions_dir = obo_sessions_dir(base_dir)
    if not sessions_dir.exists():
        return json.dumps({"sessions": [], "message": "No obo_sessions directory found"})

    rows = list_sessions(sessions_dir, status_filter=status_filter)
    return json.dumps({"sessions": rows, "total": len(rows)}, indent=2)


# ---------------------------------------------------------------------------
# Tool: obo_session_status
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_session_status(
    session_file: str,
    base_dir: Optional[str] = None,
) -> str:
    """Return summary statistics for an OBO session.

    Args:
        session_file: Absolute path or filename relative to {base_dir}/.github/obo_sessions/
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        stats = session_status(sf)
        return json.dumps(stats, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_next
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_next(
    session_file: str,
    base_dir: Optional[str] = None,
) -> str:
    """Return the next item to work on.

    Returns in_progress items first (highest priority_score), then pending.

    Args:
        session_file: Absolute path or filename relative to {base_dir}/.github/obo_sessions/
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        item = get_next(sf)
        if item is None:
            return json.dumps({"message": "No pending items — session complete!"})
        return json.dumps(item, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_list_items
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_list_items(
    session_file: str,
    base_dir: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> str:
    """List all items in a session, sorted by priority_score descending.

    Args:
        session_file: Absolute path or filename relative to {base_dir}/.github/obo_sessions/
        base_dir: Required if session_file is a bare filename
        status_filter: Optional — 'pending', 'in_progress', 'completed', 'skipped'
    """
    try:
        sf = _resolve(session_file, base_dir)
        items = list_items(sf, status_filter=status_filter)
        return json.dumps({"items": items, "total": len(items)}, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_get_item
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_get_item(
    session_file: str,
    item_id: str,
    base_dir: Optional[str] = None,
) -> str:
    """Return full detail for a single item.

    Args:
        session_file: Absolute path or filename relative to {base_dir}/.github/obo_sessions/
        item_id: Item ID (integer or string)
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        item = get_item(sf, item_id)
        if item is None:
            return f"ERROR: Item {item_id} not found"
        return json.dumps(item, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_mark_complete
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_mark_complete(
    session_file: str,
    item_id: str,
    resolution: str,
    base_dir: Optional[str] = None,
) -> str:
    """Mark an item as completed with resolution text.

    Args:
        session_file: Absolute path or filename relative to {base_dir}/.github/obo_sessions/
        item_id: Item ID to mark complete
        resolution: Text describing how the item was resolved
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        session = mark_complete(sf, item_id, resolution)
        items = session.get("items", [])
        completed = len([i for i in items if i.get("status") == "completed"])
        total = len(items)
        return json.dumps({
            "status": "ok",
            "item_id": item_id,
            "action": "completed",
            "resolution": resolution,
            "progress": f"{completed}/{total}",
        }, indent=2)
    except KeyError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_mark_skip
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_mark_skip(
    session_file: str,
    item_id: str,
    base_dir: Optional[str] = None,
    reason: Optional[str] = None,
) -> str:
    """Mark an item as skipped.

    Args:
        session_file: Absolute path or filename relative to {base_dir}/.github/obo_sessions/
        item_id: Item ID to skip
        base_dir: Required if session_file is a bare filename
        reason: Optional reason for skipping
    """
    try:
        sf = _resolve(session_file, base_dir)
        session = mark_skip(sf, item_id, reason or "")
        items = session.get("items", [])
        skipped = len([i for i in items if i.get("status") == "skipped"])
        return json.dumps({
            "status": "ok",
            "item_id": item_id,
            "action": "skipped",
            "reason": reason,
            "total_skipped": skipped,
        }, indent=2)
    except KeyError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_update_field
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_update_field(
    session_file: str,
    item_id: str,
    field: str,
    value: str,
    base_dir: Optional[str] = None,
) -> str:
    """Update any field on an item. Auto-recalculates priority_score when a
    score component (urgency, importance, effort, dependencies) is changed.

    Args:
        session_file: Absolute path or filename relative to {base_dir}/.github/obo_sessions/
        item_id: Item ID to update
        field: Field name (e.g. 'urgency', 'title', 'description', 'status')
        value: New value (always passed as string; numeric fields are cast automatically)
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        item = update_field(sf, item_id, field, value)
        result: dict = {
            "status": "ok",
            "item_id": item_id,
            "field": field,
            "new_value": item.get(field),
        }
        if field in {"urgency", "importance", "effort", "dependencies"}:
            result["priority_score"] = item.get("priority_score")
        return json.dumps(result, indent=2)
    except KeyError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
