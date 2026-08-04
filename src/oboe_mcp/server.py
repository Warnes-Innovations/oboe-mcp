# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
Oboe MCP Server — 22 tools for One-By-One session management.

Uses MCPServer for concise tool registration.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional, Sequence

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from oboe_mcp.migrate import format_result, migrate_project
from oboe_mcp.locking import (
    DEFAULT_TIMEOUT,
    LockError,
    get_default_policy,
    set_default_policy,
    supports_shared_locks,
)
from oboe_mcp.session import (
    cancel_session,
    complete_child_session,
    complete_session,
    create_child_session,
    create_session,
    get_item,
    get_next,
    list_items,
    list_sessions,
    load_session,
    mark_blocked,
    mark_complete,
    mark_deferred,
    mark_in_progress as mark_in_progress_fn,
    mark_skip,
    merge_items,
    oboe_sessions_dir,
    reindex,
    set_approval,
    session_status,
    trim_sessions,
    update_field,
    validate_session_filename,
    _open_count,
)

mcp = MCPServer("oboe-mcp", instructions="One-By-One session management tools")


# ---------------------------------------------------------------------------
# Last-resort error boundary
# ---------------------------------------------------------------------------

def _tool_boundary(fn):
    """Turn any exception a tool did not handle into a labelled error string.

    Each tool catches what it *expects*; `_TOOL_EXCEPTIONS` covers OSError,
    ValueError, JSONDecodeError and LockError.  Everything else — KeyError,
    TypeError, AttributeError — propagated raw to the MCP client, which is
    what issue #20 looked like from the outside:

        Error executing tool oboe_create: unsupported operand type(s) for +

    A raw interpreter error tells the caller nothing it can act on, and 14 of
    the 23 tools did not even catch KeyError.  This is a backstop, not a
    substitute for handling: the message says *internal error* and names the
    exception type, so a defect that reaches here still reads as a defect
    rather than as ordinary input rejection.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - deliberate outermost catch
            return (
                f"ERROR: internal error in {fn.__name__} "
                f"({type(exc).__name__}): {exc}"
            )
    return wrapper


def tool():
    """Register an MCP tool behind :func:`_tool_boundary`."""
    def decorate(fn):
        return mcp.tool()(_tool_boundary(fn))
    return decorate


# ---------------------------------------------------------------------------
# Item input schema
# ---------------------------------------------------------------------------
#
# Every tool that accepts caller-supplied items publishes this schema, so a
# client can see that the four priority factors are NUMBERS before it sends a
# sentence.  `dependencies` reads like "what this item depends on", and that
# misreading is what issue #20 was: a descriptive string reached the
# priority_score arithmetic and crashed it.
#
# The schema is advisory — MCP clients are not obliged to enforce it — so
# session.validate_score_components() re-checks every value on arrival.

_SCORE_FIELD_DOC = {
    "urgency": "How time-sensitive this item is. Higher sorts first.",
    "importance": "How much this item matters. Higher sorts first.",
    "effort": (
        "How much work this item is. Higher means MORE work and sorts "
        "LATER (the score uses 6 - effort)."
    ),
    "dependencies": (
        "How much other work is waiting on this item — dependency "
        "PRESSURE, as a number. NOT a description of what this item "
        "depends on. Higher sorts first."
    ),
}

_SCORE_DEFAULTS = {
    "urgency": 3, "importance": 3, "effort": 3, "dependencies": 1,
}

ITEM_INPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "id": {
            "type": ["string", "integer"],
            "description": (
                "Item identifier. Assigned sequentially from 1 if omitted."
            ),
        },
        "title": {"type": "string", "description": "Short label."},
        "description": {"type": "string", "description": "Free-text detail."},
        "category": {"type": "string", "description": "Category label."},
        "status": {
            "type": "string",
            "enum": [
                "pending", "in_progress", "deferred",
                "blocked", "completed", "skipped",
            ],
            "description": "Lifecycle status. Defaults to 'pending'.",
        },
        **{
            field: {
                "type": "number",
                "minimum": 0,
                "maximum": 5,
                "default": _SCORE_DEFAULTS[field],
                "description": (
                    f"Priority factor, integer 0-5 (default "
                    f"{_SCORE_DEFAULTS[field]}). {doc}"
                ),
            }
            for field, doc in _SCORE_FIELD_DOC.items()
        },
    },
    "additionalProperties": True,
}

_ITEMS_DESCRIPTION = (
    "List of item dicts. All fields are optional. The four priority factors "
    "-- urgency, importance, effort, dependencies -- are NUMBERS in the range "
    "0-5, not text; a non-numeric value is rejected naming the item and the "
    "field. In particular 'dependencies' is a numeric measure of dependency "
    "pressure, NOT a description of what the item depends on -- put that in "
    "'description'. priority_score = urgency + importance + (6 - effort) + "
    "dependencies."
)


def _inject_item_schema(schema: dict) -> None:
    """Attach ITEM_INPUT_SCHEMA to a ``list[dict]`` parameter's schema.

    Pydantic renders ``Optional[list[dict]]`` as an ``anyOf`` of an array
    branch and a null branch, so the array branch is what needs the item
    schema; a required ``list[dict]`` has no ``anyOf`` and is patched directly.
    """
    for branch in schema.get("anyOf", []):
        if branch.get("type") == "array":
            branch["items"] = ITEM_INPUT_SCHEMA
    if schema.get("type") == "array":
        schema["items"] = ITEM_INPUT_SCHEMA


_ITEMS_FIELD = Field(
    description=_ITEMS_DESCRIPTION,
    json_schema_extra=_inject_item_schema,
)

ItemList = Annotated[list[dict], _ITEMS_FIELD]
OptionalItemList = Annotated[Optional[list[dict]], _ITEMS_FIELD]

# LockError is included so a contended session surfaces to the calling agent
# as a normal tool error it can act on, rather than an unhandled exception.
_TOOL_EXCEPTIONS = (OSError, ValueError, json.JSONDecodeError, LockError)

_REMOTE_SSH_HINT = """\

This often happens when the oboe-mcp server is running on your LOCAL machine
but your VS Code workspace is on a REMOTE host (SSH, Dev Container, Codespaces).

In that case, the path you passed exists on the remote host but not locally,
so the server cannot access it.

Workaround: run oboe-mcp on the remote host instead by adding a
workspace-level .vscode/mcp.json to your remote repository:

  {
    "servers": {
      "oboe-mcp": {
        "type": "stdio",
        "command": "uvx",
        "args": ["oboe-mcp"]
      }
    }
  }

This requires uv to be installed on the remote host:
  curl -LsSf https://astral.sh/uv/install.sh | sh

Once in place, VS Code Remote will launch oboe-mcp on the remote host,
where it can access the workspace paths directly.
See: https://github.com/Warnes-Innovations/oboe-mcp/issues/5"""


# ---------------------------------------------------------------------------
# Helper: validate base_dir exists
# ---------------------------------------------------------------------------

def _validate_base_dir(base_dir: str) -> None:
    """Raise ValueError with a helpful diagnostic if base_dir does not exist."""
    if not os.path.exists(base_dir):
        raise ValueError(
            f"base_dir does not exist: {base_dir}\n"
            + _REMOTE_SSH_HINT
        )


# ---------------------------------------------------------------------------
# Helper: resolve session_file argument
# ---------------------------------------------------------------------------

def _resolve(session_file: str, base_dir: str | None = None) -> Path:
    """Resolve session_file (absolute path or bare filename) to a Path."""
    p = Path(session_file)
    if p.is_absolute():
        return p
    if base_dir:
        _validate_base_dir(base_dir)
        sessions_dir = oboe_sessions_dir(base_dir)
        # Defensive: if session_file is already a path under sessions_dir, don't join again
        session_path = Path(session_file)
        if session_path.parent == sessions_dir:
            return session_path.resolve()
        return (sessions_dir / session_file).resolve()
    raise ValueError(
        "session_file must be an absolute path or base_dir (project root) must be provided. "
        "base_dir should be the project root, not .github/obo_sessions."
    )


# ---------------------------------------------------------------------------
# Tool: oboe_create
# ---------------------------------------------------------------------------

@tool()
def oboe_create(
    base_dir: str,
    title: str,
    description: str,
    items: OptionalItemList = None,
    session_file: Optional[str] = None,
) -> str:
    """Create a new OBO session file and update index.json atomically.

    Args:
        base_dir: Project root directory.
        title: Human-readable session title
        description: What this session is reviewing
        items: List of item dicts. Every field is optional; if items is
               omitted entirely the session is created empty (items can be
               added later with oboe_merge_items).

               The four priority factors are NUMBERS in the range 0-5:

                 urgency      integer 0-5, default 3 — time sensitivity
                 importance   integer 0-5, default 3 — how much it matters
                 effort       integer 0-5, default 3 — how much work it is
                 dependencies integer 0-5, default 1 — how much other work
                              is waiting on this item (dependency PRESSURE)

               'dependencies' is a numeric score, NOT a description of what
               the item depends on — that belongs in 'description'. A
               non-numeric or out-of-range value is rejected with an error
               naming the item and the field; nothing is written.

               priority_score = urgency + importance + (6 - effort)
                                + dependencies

               Higher effort therefore lowers the score. Other accepted
               fields: id, title, description, category, status.
        session_file: Optional explicit filename.
                      If omitted, generated from current timestamp.
    """
    try:
        _validate_base_dir(base_dir)
    except ValueError as e:
        return f"ERROR: {e}"
    sessions_dir = oboe_sessions_dir(base_dir)
    try:
        if session_file:
            validate_session_filename(session_file)
            sf = sessions_dir / session_file
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
# Tool: oboe_reindex
# ---------------------------------------------------------------------------

@tool()
def oboe_reindex(base_dir: str, write: bool = True) -> str:
    """Rebuild index.json from the session files on disk.

    Every other index repair in oboe is CONDITIONAL — it fires only when the
    index is missing, corrupt, or structurally invalid.  That leaves one case
    uncovered: an index that is perfectly VALID but no longer COMPLETE.  Such an
    index is indistinguishable from a correct one to every other code path, so
    nothing repairs it and nothing reports it, and oboe_list_sessions will
    happily return the stale subset.

    Use this when the session list looks wrong, after restoring or reverting
    index.json, or after moving session files between directories.

    Args:
        base_dir: Project root directory
        write: True (default) rebuilds and saves. False computes the diff and
               reports it WITHOUT writing — a check mode for CI or a
               pre-commit hook.

    Returns a summary with added/removed/updated filename lists, before/after
    counts, any unreadable session files, and `changed` (False when the index
    was already accurate).
    """
    try:
        _validate_base_dir(base_dir)
    except ValueError as e:
        return f"ERROR: {e}"
    sessions_dir = oboe_sessions_dir(base_dir)
    if not sessions_dir.exists():
        return json.dumps(
            {"sessions": [], "message": "No oboe_sessions directory found"}
        )

    return json.dumps(reindex(sessions_dir, write=write), indent=2)


# ---------------------------------------------------------------------------
# Tool: oboe_list_sessions
# ---------------------------------------------------------------------------

@tool()
def oboe_list_sessions(
    base_dir: str,
    status_filter: Optional[str] = None,
) -> str:
    """List OBO sessions from index.json.

    Args:
        base_dir: Project root directory
        status_filter: Optional filter — 'active', 'paused', 'completed',
                       'cancelled', or 'incomplete' (incomplete = active or
                       paused sessions with open items).  Vocabulary note:
                       'incomplete' is specific to this tool; oboe_trim_sessions
                       uses 'any' (not 'incomplete') to mean all statuses.
    """
    try:
        _validate_base_dir(base_dir)
    except ValueError as e:
        return f"ERROR: {e}"
    sessions_dir = oboe_sessions_dir(base_dir)
    if not sessions_dir.exists():
        return json.dumps(
            {"sessions": [], "message": "No oboe_sessions directory found"}
        )

    rows = list_sessions(sessions_dir, status_filter=status_filter)
    return json.dumps({"sessions": rows, "total": len(rows)}, indent=2)


# ---------------------------------------------------------------------------
# Tool: oboe_session_status
# ---------------------------------------------------------------------------

@tool()
def oboe_session_status(
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
# Tool: oboe_get_session
# ---------------------------------------------------------------------------

@tool()
def oboe_get_session(
    session_file: str,
    base_dir: Optional[str] = None,
) -> str:
    """Return header metadata for a session (title, description, dates, relationships).

    Unlike oboe_session_status (which returns item counts), this returns the
    full session header: title, description, created, status,
    parent_session_file, parent_item_id, child_session_files, and
    active_child_session.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        base_dir: Required if session_file is a bare filename
    """
    try:
        sf = _resolve(session_file, base_dir)
        session = load_session(sf)
        header = {
            "session_file":        session.get("session_file"),
            "title":               session.get("title"),
            "description":         session.get("description"),
            "status":              session.get("status"),
            "created":             session.get("created"),
            "completed_at":        session.get("completed_at"),
            "cancelled_at":        session.get("cancelled_at"),
            "cancel_reason":       session.get("cancel_reason"),
            "parent_session_file": session.get("parent_session_file"),
            "parent_item_id":      session.get("parent_item_id"),
            "child_session_files": session.get("child_session_files", []),
            "active_child_session": session.get("active_child_session"),
        }
        return json.dumps(header, indent=2)
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: oboe_next
# ---------------------------------------------------------------------------

@tool()
def oboe_next(
    session_file: str,
    base_dir: Optional[str] = None,
    mark_in_progress: bool = False,
) -> str:
    """Return the next item to work on.

    Returns in_progress items first, then pending, then deferred.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        base_dir: Required if session_file is a bare filename
        mark_in_progress: If True, atomically mark the returned item as
                          in_progress before returning it.  Eliminates a
                          separate oboe_mark_in_progress call.
    """
    try:
        sf = _resolve(session_file, base_dir)
        try:
            item = get_next(sf)
        except ValueError as e:
            msg = str(e)
            if "paused by active child session" in msg:
                # Extract the child session filename from the error message
                child_name = msg.split(": ", 1)[-1] if ": " in msg else ""
                return json.dumps({
                    "status": "paused",
                    "message": (
                        "This session is paused while a child session is active. "
                        "Work through the child session items, then call "
                        "oboe_complete_child_session to resume this parent session."
                    ),
                    "active_child_session": child_name,
                    "action_required": (
                        f"Call oboe_next with session_file='{child_name}' "
                        "to continue work on the child session."
                    ),
                }, indent=2)
            return f"ERROR: {e}"
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
                    "action_required": (
                        "Call oboe_list_items with status_filter='blocked' "
                        "to review and resolve blockers."
                    ),
                }, indent=2)
            return json.dumps(
                {"message": "No pending items — session complete!"}
            )
        stats = session_status(sf)
        total     = stats.get("total", 0)
        completed = stats.get("completed", 0) + stats.get("skipped", 0)
        remaining = stats.get("pending", 0) + stats.get("in_progress", 0) + stats.get("deferred", 0)
        result = dict(item)
        result["progress"] = {
            "completed": completed,
            "total":     total,
            "remaining": remaining,
        }
        if mark_in_progress and item.get("status") != "in_progress":
            mark_in_progress_fn(sf, item["id"])
            result["status"] = "in_progress"
        return json.dumps(result, indent=2)
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: oboe_list_items
# ---------------------------------------------------------------------------

@tool()
def oboe_list_items(
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
# Tool: oboe_get_item
# ---------------------------------------------------------------------------

@tool()
def oboe_get_item(
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
# Tool: oboe_mark_complete
# ---------------------------------------------------------------------------

@tool()
def oboe_mark_complete(
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
        completed = len([i for i in items if i.get("status") in {"completed", "skipped"}])
        total = len(items)
        remaining = total - completed
        return json.dumps({
            "status": "ok",
            "item_id": item_id,
            "action": "completed",
            "resolution": resolution,
            "progress": {
                "completed": completed,
                "total":     total,
                "remaining": remaining,
            },
        }, indent=2)
    except KeyError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: oboe_mark_skip
# ---------------------------------------------------------------------------

@tool()
def oboe_mark_skip(
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
# Tool: oboe_mark_deferred
# ---------------------------------------------------------------------------

@tool()
def oboe_mark_deferred(
    session_file: str,
    item_id: str,
    base_dir: Optional[str] = None,
    reason: Optional[str] = None,
    deferred_until: Optional[str] = None,
) -> str:
    """Mark an item as deferred (intentionally postponed).

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        item_id: Item ID to defer
        base_dir: Required if session_file is a bare filename
        reason: Optional reason for deferring
        deferred_until: Optional date hint (ISO-8601) for when to revisit
    """
    try:
        sf = _resolve(session_file, base_dir)
        item = mark_deferred(sf, item_id, reason or "", deferred_until or "")
        return json.dumps({
            "status": "ok",
            "item_id": item_id,
            "action": "deferred",
            "reason": reason,
            "deferred_until": deferred_until,
        }, indent=2)
    except KeyError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: oboe_mark_blocked
# ---------------------------------------------------------------------------

@tool()
def oboe_mark_blocked(
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
# Tool: oboe_set_approval
# ---------------------------------------------------------------------------

@tool()
def oboe_set_approval(
    session_file: str,
    item_id: str,
    approval_status: str,
    base_dir: Optional[str] = None,
    approval_mode: Optional[str] = None,
    approval_note: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
) -> str:
    """Set approval metadata and optional lifecycle state for an item.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        item_id: Item ID to update
        approval_status: Approval value: 'unreviewed', 'approved', or 'denied'
        base_dir: Required if session_file is a bare filename
        approval_mode: Optional timing mode: 'immediate' or 'delayed'
        approval_note: Optional approval note to store on the item
        lifecycle_status: Optional lifecycle status to set alongside approval
    """
    try:
        sf = _resolve(session_file, base_dir)
        item = set_approval(
            sf,
            item_id,
            approval_status,
            approval_mode=approval_mode,
            note=approval_note,
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
# Tool: oboe_update_field
# ---------------------------------------------------------------------------


@tool()
def oboe_mark_in_progress(
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
        session = mark_in_progress_fn(sf, item_id)
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


@tool()
def oboe_complete_session(
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
        items = session.get("items", [])
        total     = len(items)
        completed = sum(1 for i in items if i.get("status") == "completed")
        skipped   = sum(1 for i in items if i.get("status") == "skipped")
        return json.dumps({
            "status": "ok",
            "action": "session_completed",
            "session_file": sf.name,
            "session_status": session.get("status", "completed"),
            "completed": completed,
            "skipped":   skipped,
            "total":     total,
        }, indent=2)
    except ValueError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


@tool()
def oboe_create_child_session(
    parent_session_file: str,
    title: str,
    description: str,
    items: OptionalItemList = None,
    base_dir: Optional[str] = None,
    parent_item_id: Optional[str] = None,
    session_file: Optional[str] = None,
) -> str:
    """Create a child session, pause the parent, and step into the child.

    Args:
        parent_session_file: Parent session path or filename
        title: Human-readable child session title
        description: What the child session is reviewing
        items: Child session items, same shape as oboe_create. If omitted,
               the child session is created with no items (items can be added
               later with oboe_merge_items). The four priority factors
               (urgency, importance, effort, dependencies) are NUMBERS in the
               range 0-5, not text.
        base_dir: Required if session paths are bare filenames
        parent_item_id: Optional parent item to block while child is active
        session_file: Optional explicit child session filename
    """
    try:
        parent_sf = _resolve(parent_session_file, base_dir)
        sessions_dir = parent_sf.parent
        if session_file:
            validate_session_filename(session_file)
            child_sf = sessions_dir / session_file
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


@tool()
def oboe_complete_child_session(
    child_session_file: str,
    base_dir: Optional[str] = None,
    resolution: str = "",
    disposition: str = "completed",
) -> str:
    """Close a child session and resume its parent session.

    Args:
        child_session_file: Child session path or filename
        base_dir: Required if session paths are bare filenames
        resolution: Optional note stored on the unblocked parent item
        disposition: ``"completed"`` (default — all items must be done) or
                     ``"cancelled"`` (child abandoned; open items allowed).
                     In both cases the parent item is unblocked.
    """
    try:
        child_sf = _resolve(child_session_file, base_dir)
        result = complete_child_session(
            child_sf, resolution=resolution, disposition=disposition
        )
        child_session = result["child_session"]
        parent_session = result["parent_session"]
        return json.dumps({
            "status": "ok",
            "action": f"child_{disposition}",
            "child_session_file": child_sf.name,
            "child_status": child_session.get("status"),
            "parent_session_file": child_session.get("parent_session_file"),
            "parent_status": parent_session.get("status"),
            "active_child_session": parent_session.get("active_child_session"),
        }, indent=2)
    except (ValueError, KeyError) as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


@tool()
def oboe_merge_items(
    session_file: str,
    items: ItemList,
    base_dir: Optional[str] = None,
) -> str:
    """Append new items to an existing session.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        items: List of item dicts to append. Same shape as oboe_create: the
               four priority factors (urgency, importance, effort,
               dependencies) are NUMBERS in the range 0-5, not text, and
               'dependencies' measures dependency pressure rather than
               naming what the item depends on. A bad value rejects the
               whole batch, naming the item and the field; no items are
               appended.
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


@tool()
def oboe_update_field(
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
        field: Field name. Must be one of the documented item fields:
               title, category, description, status, urgency, importance,
               effort, dependencies, priority_score, resolution, skip_reason,
               blocker, blocked_at, approval_status, approval_mode,
               approved_at, approval_note, child_session_resolution.
               An unrecognised name is rejected rather than stored.
               'id' cannot be changed — an id collision would make one of the
               two items permanently unreachable.
        value: New value, as a string. The four score components (urgency,
               importance, effort, dependencies) must parse as a whole number
               in the range 0-5 — "4" is fine, "high" or "blocks the cutover"
               is rejected with an error naming the item and the field.
               'dependencies' is dependency PRESSURE as a number, not a
               description of what the item depends on.
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


@tool()
def oboe_cancel_session(
    session_file: str,
    base_dir: Optional[str] = None,
    cancel_reason: str = "",
) -> str:
    """Mark a session cancelled. Open items are left as-is.

    Args:
        session_file: Absolute path or filename relative to the sessions dir.
        base_dir: Required if session_file is a bare filename
        cancel_reason: Optional human-readable reason for cancellation
    """
    try:
        sf = _resolve(session_file, base_dir)
        session = cancel_session(sf, reason=cancel_reason)
        return json.dumps({
            "status": "ok",
            "action": "session_cancelled",
            "session_file": sf.name,
            "session_status": session.get("status", "cancelled"),
            "open_items_remaining": _open_count(session),
            "cancel_reason": session.get("cancel_reason") or "",
        }, indent=2)
    except ValueError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


@tool()
def oboe_trim_sessions(
    base_dir: str,
    before: Optional[str] = None,
    status_filter: str = "completed",
    dry_run: bool = False,
) -> str:
    """Delete session files matching status and/or age criteria.

    Args:
        base_dir: Project root directory (sessions live in
                  .github/oboe_sessions/ under this path)
        before: ISO-8601 datetime string, or 'now' to delete all matching
                sessions. Sessions created before this timestamp are deleted.
                Omit to match any age.
        status_filter: 'completed', 'cancelled', 'active', 'paused', or
                       'any' (no status restriction).  Default: 'completed'.
                       Vocabulary note: use 'any' here for "all statuses";
                       the term 'incomplete' used by oboe_list_sessions is
                       not accepted here to prevent accidental deletion of
                       active sessions.
        dry_run: If true, report what would be deleted without deleting.
    """
    try:
        sessions_dir = oboe_sessions_dir(Path(base_dir))
        sf = None if status_filter == "any" else status_filter
        result = trim_sessions(
            sessions_dir,
            before=before or None,
            status_filter=sf,
            dry_run=dry_run,
        )
        return json.dumps({
            "status": "ok",
            "action": "dry_run" if dry_run else "trimmed",
            **result,
        }, indent=2)
    except ValueError as e:
        return f"ERROR: {e}"
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: oboe_set_lock_policy
# ---------------------------------------------------------------------------
@tool()
def oboe_set_lock_policy(
    blocking: bool = True,
    timeout_seconds: Optional[float] = DEFAULT_TIMEOUT,
) -> str:
    """Choose what happens when another process holds the session lock.

    Session files are shared with the oboe-cli and with any other editor
    window or agent pointed at the same project, so an operation can find the
    store locked.  This sets the policy for subsequent tool calls on this
    server; it does not need to be called at all if the default suits you.

    Args:
        blocking: True (default) waits for the lock. False fails immediately
                  with an error when the lock is held, which suits an agent
                  that would rather retry later than stall.
        timeout_seconds: How long to wait when blocking. Omit for the default
                  of 30s. Pass 0 or a negative number to wait indefinitely —
                  note that a wedged holder will then hang the call with no
                  diagnostic.
    """
    try:
        timeout: float | None
        if timeout_seconds is None:
            timeout = DEFAULT_TIMEOUT
        elif timeout_seconds <= 0:
            timeout = None
        else:
            timeout = float(timeout_seconds)

        applied = set_default_policy(blocking=blocking, timeout=timeout)
        return json.dumps({
            "status": "ok",
            "action": "lock_policy_set",
            "blocking": applied.blocking,
            "timeout_seconds": applied.timeout,
            "policy": applied.describe(),
            "concurrent_readers": supports_shared_locks(),
            "note": (
                "Applies to subsequent oboe_* calls on this server process. "
                "Other processes (oboe-cli, another editor window) keep their "
                "own policy."
            ),
        }, indent=2)
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: oboe_get_lock_policy
# ---------------------------------------------------------------------------
@tool()
def oboe_get_lock_policy() -> str:
    """Report the lock policy currently in effect for this server process."""
    try:
        current = get_default_policy()
        return json.dumps({
            "status": "ok",
            "blocking": current.blocking,
            "timeout_seconds": current.timeout,
            "policy": current.describe(),
            "concurrent_readers": supports_shared_locks(),
        }, indent=2)
    except _TOOL_EXCEPTIONS as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the console entry point.

    Running ``oboe-mcp`` with no subcommand starts the stdio server, which is
    how MCP clients invoke it.  Subcommands are therefore optional and must
    never become required.
    """
    parser = argparse.ArgumentParser(
        prog="oboe-mcp",
        description=(
            "Run the Oboe MCP stdio server for one-by-one session "
            "management tools. With no subcommand, starts the server."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    migrate_parser = sub.add_parser(
        "migrate",
        help="Migrate a project from obo_ tool names to oboe_ (v0.3.0+)",
        description=(
            "Rewrite a project's agent instruction files and session "
            "directory from the pre-0.3.0 obo_ names to oboe_. Safe to run "
            "more than once."
        ),
    )
    migrate_parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="Project root to migrate (default: current directory)",
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying anything",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the MCP server, or a subcommand if one was given."""
    args = _build_parser().parse_args(argv)

    if getattr(args, "command", None) == "migrate":
        try:
            result = migrate_project(args.project_root, dry_run=args.dry_run)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(format_result(result))
        return 0

    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
