# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
Oboe MCP Server — 16 tools for One-By-One session management.

Uses FastMCP for concise tool registration.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from mcp.server.fastmcp import FastMCP

from oboe_mcp.session import (
    complete_child_session,
    complete_session,
    create_child_session,
    create_session,
    get_item,
    get_next,
    list_items,
    list_sessions,
    mark_blocked,
    mark_complete,
    mark_in_progress,
    mark_skip,
    merge_items,
    obo_sessions_dir,
    set_approval,
    session_status,
    update_field,
    validate_session_filename,
)

mcp = FastMCP("oboe-mcp", instructions="One-By-One session management tools")

_TOOL_EXCEPTIONS = (OSError, ValueError, json.JSONDecodeError)


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
    items: Optional[list[dict]] = None,
    session_filename: Optional[str] = None,
) -> str:
    """Create a new OBO session file and update index.json atomically.

    Args:
        base_dir: Project root directory.
        title: Human-readable session title
        description: What this session is reviewing
        items: List of item dicts. All priority fields are optional.
               If omitted, the session is created with no items (items can
               be added later with obo_merge_items).
        session_filename: Optional explicit filename.
                          If omitted, generated from current timestamp.
    """
    sessions_dir = obo_sessions_dir(base_dir)
    try:
        if session_filename:
            validate_session_filename(session_filename)
            sf = sessions_dir / session_filename
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            sf = sessions_dir / f"session_{ts}.json"

        session = create_session(
            sf,
            items if items is not None else [],
            title=title,
            description=description,
        )
    except (FileExistsError, ValueError) as e:
        return f"ERROR: {e}"

    return json.dumps({
        "session_file": sf.name,
        "path": str(sf),
        "title": session["title"],
        "items_created": len(session["items"]),
        "status": session["status"],
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
        status_filter: Optional filter — 'active', 'paused', 'completed',
                       or 'incomplete' (incomplete = active or paused sessions
                       with open items)
    """
    sessions_dir = obo_sessions_dir(base_dir)
    if not sessions_dir.exists():
        return json.dumps(
            {"sessions": [], "message": "No obo_sessions directory found"}
        )

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
        session_file: Absolute path or filename relative to the sessions dir.
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        stats = session_status(sf)
        return json.dumps(stats, indent=2)
    except _TOOL_EXCEPTIONS as e:
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

    Returns in_progress items first, then pending, then deferred.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        item = get_next(sf)
        if item is None:
            stats = session_status(sf)
            if stats.get("blocked", 0) > 0:
                return json.dumps({
                    "message": (
                        "No actionable items remain; all unresolved items are "
                        "blocked"
                    ),
                    "blocked": stats.get("blocked", 0),
                    "active_child_session": stats.get("active_child_session"),
                }, indent=2)
            return json.dumps(
                {"message": "No pending items — session complete!"}
            )
        return json.dumps(item, indent=2)
    except _TOOL_EXCEPTIONS as e:
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
        session_file: Absolute path or filename relative to the sessions dir.
        base_dir: Required if session_file is a bare filename
        status_filter: Optional item status filter.
    """
    try:
        sf = _resolve(session_file, base_dir)
        items = list_items(sf, status_filter=status_filter)
        return json.dumps({"items": items, "total": len(items)}, indent=2)
    except _TOOL_EXCEPTIONS as e:
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
        session_file: Absolute path or filename relative to the sessions dir.
        item_id: Item ID (integer or string)
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        item = get_item(sf, item_id)
        if item is None:
            return f"ERROR: Item {item_id} not found"
        return json.dumps(item, indent=2)
    except _TOOL_EXCEPTIONS as e:
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
        session_file: Absolute path or filename relative to the sessions dir.
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
    except _TOOL_EXCEPTIONS as e:
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
        session_file: Absolute path or filename relative to the sessions dir.
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
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_mark_blocked
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_mark_blocked(
    session_file: str,
    item_id: str,
    blocker: str,
    base_dir: Optional[str] = None,
) -> str:
    """Mark an item blocked and store blocker information.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        item_id: Item ID to mark blocked
        blocker: Description of what is blocking progress
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        session = mark_blocked(sf, item_id, blocker)
        items = session.get("items", [])
        blocked = len([i for i in items if i.get("status") == "blocked"])
        item = next(i for i in items if str(i.get("id")) == str(item_id))
        return json.dumps({
            "status": "ok",
            "item_id": item_id,
            "action": "blocked",
            "blocker": item.get("blocker"),
            "total_blocked": blocked,
            "session_status": session.get("status", "active"),
        }, indent=2)
    except KeyError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_set_approval
# ---------------------------------------------------------------------------

@mcp.tool()
def obo_set_approval(
    session_file: str,
    item_id: str,
    approval_status: str,
    base_dir: Optional[str] = None,
    approval_mode: Optional[str] = None,
    note: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
) -> str:
    """Set approval metadata and optional lifecycle state for an item.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        item_id: Item ID to update
        approval_status: Approval value: 'unreviewed', 'approved', or 'denied'
        base_dir: Required if session_file is a bare filename
        approval_mode: Optional timing mode: 'immediate' or 'delayed'
        note: Optional approval note to store on the item
        lifecycle_status: Optional lifecycle status to set alongside approval
    """
    try:
        sf = _resolve(session_file, base_dir)
        item = set_approval(
            sf,
            item_id,
            approval_status,
            approval_mode=approval_mode,
            note=note,
            lifecycle_status=lifecycle_status,
        )
        return json.dumps({
            "status": "ok",
            "item_id": item_id,
            "action": "approval_updated",
            "approval_status": item.get("approval_status"),
            "approval_mode": item.get("approval_mode"),
            "approved_at": item.get("approved_at"),
            "approval_note": item.get("approval_note"),
            "lifecycle_status": item.get("status"),
        }, indent=2)
    except KeyError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: obo_update_field
# ---------------------------------------------------------------------------


@mcp.tool()
def obo_mark_in_progress(
    session_file: str,
    item_id: str,
    base_dir: Optional[str] = None,
) -> str:
    """Mark an item as in progress.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        item_id: Item ID to mark in progress
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        session = mark_in_progress(sf, item_id)
        items = session.get("items", [])
        in_progress = len(
            [i for i in items if i.get("status") == "in_progress"]
        )
        return json.dumps({
            "status": "ok",
            "item_id": item_id,
            "action": "in_progress",
            "total_in_progress": in_progress,
            "session_status": session.get("status", "active"),
        }, indent=2)
    except KeyError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


@mcp.tool()
def obo_complete_session(
    session_file: str,
    base_dir: Optional[str] = None,
) -> str:
    """Mark a session completed when no actionable items remain.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        session = complete_session(sf)
        return json.dumps({
            "status": "ok",
            "action": "session_completed",
            "session_file": sf.name,
            "session_status": session.get("status", "completed"),
        }, indent=2)
    except ValueError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


@mcp.tool()
def obo_create_child_session(
    parent_session_file: str,
    title: str,
    description: str,
    items: Optional[list[dict]] = None,
    base_dir: Optional[str] = None,
    parent_item_id: Optional[str] = None,
    session_filename: Optional[str] = None,
) -> str:
    """Create a child session, pause the parent, and step into the child.

    Args:
        parent_session_file: Parent session path or filename
        title: Human-readable child session title
        description: What the child session is reviewing
        items: Child session items. If omitted, the child session is created
               with no items (items can be added later with obo_merge_items).
        base_dir: Required if session paths are bare filenames
        parent_item_id: Optional parent item to block while child is active
        session_filename: Optional explicit child session filename
    """
    try:
        parent_sf = _resolve(parent_session_file, base_dir)
        sessions_dir = parent_sf.parent
        if session_filename:
            validate_session_filename(session_filename)
            child_sf = sessions_dir / session_filename
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            child_sf = sessions_dir / f"session_{ts}.json"

        result = create_child_session(
            parent_sf,
            child_sf,
            items if items is not None else [],
            title=title,
            description=description,
            parent_item_id=parent_item_id,
        )
        child_session = result["child_session"]
        parent_session = result["parent_session"]
        return json.dumps({
            "status": "ok",
            "action": "child_created",
            "parent_session_file": parent_sf.name,
            "parent_status": parent_session.get("status"),
            "parent_item_id": parent_item_id,
            "child_session_file": child_sf.name,
            "child_status": child_session.get("status"),
        }, indent=2)
    except (FileExistsError, ValueError, KeyError) as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


@mcp.tool()
def obo_complete_child_session(
    child_session_file: str,
    base_dir: Optional[str] = None,
    resolution: str = "",
) -> str:
    """Complete a child session and resume its parent session.

    Args:
        child_session_file: Child session path or filename
        base_dir: Required if session paths are bare filenames
        resolution: Optional note stored on the resumed parent item
    """
    try:
        child_sf = _resolve(child_session_file, base_dir)
        result = complete_child_session(child_sf, resolution=resolution)
        child_session = result["child_session"]
        parent_session = result["parent_session"]
        return json.dumps({
            "status": "ok",
            "action": "child_completed",
            "child_session_file": child_sf.name,
            "child_status": child_session.get("status"),
            "parent_session_file": parent_session.get("session_file"),
            "parent_status": parent_session.get("status"),
            "active_child_session": parent_session.get("active_child_session"),
        }, indent=2)
    except (ValueError, KeyError) as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


@mcp.tool()
def obo_merge_items(
    session_file: str,
    items: list[dict],
    base_dir: Optional[str] = None,
) -> str:
    """Append new items to an existing session.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        items: List of item dicts to append to the session
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        result = merge_items(sf, items)
        session = result["session"]
        merged_items = result["merged_items"]
        return json.dumps({
            "status": "ok",
            "action": "merged",
            "session_file": sf.name,
            "merged_count": len(merged_items),
            "total_items": len(session.get("items", [])),
            "session_status": session.get("status", "active"),
        }, indent=2)
    except ValueError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


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
        session_file: Absolute path or filename relative to the sessions dir.
        item_id: Item ID to update
        field: Field name (e.g. 'urgency', 'title', 'description',
               'status', 'approval_status', 'approval_mode')
        value: New value. Numeric score fields are cast automatically.
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
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the console entry point."""
    parser = argparse.ArgumentParser(
        prog="oboe-mcp",
        description=(
            "Run the Oboe MCP stdio server for one-by-one session "
            "management tools."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the MCP server CLI entry point."""
    _build_parser().parse_args(argv)
    mcp.run()


if __name__ == "__main__":
    main()
