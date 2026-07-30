# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
obo — OBO (One-By-One) session manager CLI.

A human-friendly command-line interface for managing OBO session JSON files.
All state is read and written through :mod:`oboe_mcp.session` — no direct
JSON manipulation is performed here.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

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
    mark_blocked,
    mark_complete,
    mark_in_progress,
    mark_skip,
    merge_items,
    oboe_sessions_dir,
    resolve_base_dir,
    resolve_session_file,
    session_status,
    set_approval,
    trim_sessions,
    update_field,
    validate_session_filename,
)


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

_STATUS_ICONS: dict[str, str] = {
    "completed":   "✓",
    "in_progress": "⏳",
    "skipped":     "⊘",
    "pending":     "○",
    "deferred":    "◷",
    "blocked":     "✖",
}


def _fmt_status(status: str) -> str:
    icon = _STATUS_ICONS.get(status, "?")
    return f"{icon} {status}"


def _print_sessions_table(rows: list[dict]) -> None:
    if not rows:
        print("No sessions found.")
        return
    print(
        f"\n{'File':<45} {'Status':<12} {'Open':<6} {'Done':<10} "
        f"{'Created':<12} Title"
    )
    print("=" * 110)
    for r in rows:
        total    = r.get("open", 0) + r.get("pending", 0)
        # Prefer the richer "open" field; fall back if absent
        open_n   = r.get("open", r.get("pending", 0) + r.get("in_progress", 0))
        done_n   = r.get("actionable", r.get("pending", 0))
        # Display a rough done fraction from what we have in the index row
        status   = r.get("status", "")
        print(
            f"{r.get('file', ''):<45} {status:<12} "
            f"{open_n:<6} {done_n:<10} {r.get('created', ''):<12} "
            f"{r.get('title', '')}"
        )
    print(f"\nTotal: {len(rows)} session(s)")


def _print_items_table(items: list[dict]) -> None:
    if not items:
        print("No items found.")
        return
    print(f"\n{'ID':<5} {'Score':<7} {'Status':<20} Title")
    print("=" * 80)
    for item in items:
        print(
            f"{item.get('id', ''):<5} "
            f"{item.get('priority_score', 0):<7} "
            f"{_fmt_status(item.get('status', '')):<20} "
            f"{item.get('title', '')}"
        )
    print(f"\nTotal: {len(items)} item(s)")


def _print_item_detail(item: dict) -> None:
    print("\n" + "=" * 80)
    print(f"ITEM {item.get('id')}: {item.get('title', '')}")
    print("=" * 80)
    for key, value in item.items():
        if key == "id":
            continue
        print(f"  {key:<20} {value}")
    print("=" * 80)


def _print_next(item: dict | None, stats: dict) -> None:
    total       = stats.get("total", 0)
    completed   = stats.get("completed", 0)
    in_progress = stats.get("in_progress", 0)
    pending     = stats.get("pending", 0)

    if item is None:
        print("✓ No actionable items — session is complete!")
        return

    status = item.get("status", "pending")
    if status == "in_progress":
        label = f"RESUMING IN-PROGRESS ITEM (ID: {item['id']})"
    else:
        label = f"NEXT ITEM (ID: {item['id']})"

    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)
    print(f"  Title:       {item.get('title', '')}")
    print(f"  Category:    {item.get('category', 'General')}")
    u = item.get("urgency", 0)
    i = item.get("importance", 0)
    e = item.get("effort", 0)
    d = item.get("dependencies", 0)
    print(
        f"  Priority:    {item.get('priority_score', 0)} "
        f"(U:{u} I:{i} E:{e} D:{d})"
    )
    print(f"  Description: {item.get('description', '')}")
    if item.get("blocker"):
        print(f"  Blocker:     {item['blocker']}")
    print("=" * 80)
    print(
        f"\nProgress: {completed}/{total} completed, "
        f"{in_progress} in-progress, {pending} pending"
    )


def _print_session_status(stats: dict) -> None:
    total     = stats.get("total", 0)
    completed = stats.get("completed", 0)
    skipped   = stats.get("skipped", 0)
    in_prog   = stats.get("in_progress", 0)
    pending   = stats.get("pending", 0)
    deferred  = stats.get("deferred", 0)
    blocked   = stats.get("blocked", 0)
    done      = stats.get("done", completed + skipped)
    pct       = stats.get("pct_done", (100 * done // total) if total else 0)

    print("\n" + "=" * 80)
    print(f"OBO SESSION STATUS: {stats.get('session_file', '')}")
    print("=" * 80)
    print(f"  Total:        {total}")
    print(f"  Completed:    {completed}")
    print(f"  Skipped:      {skipped}")
    print(f"  Done (c+s):   {done} ({pct}%)")
    print(f"  In Progress:  {in_prog}")
    print(f"  Deferred:     {deferred}")
    print(f"  Blocked:      {blocked}")
    print(f"  Pending:      {pending}")
    print("=" * 80)

    categories = stats.get("categories", {})
    if categories:
        print("\nBy Category:")
        for cat, counts in sorted(categories.items()):
            cat_total = counts.get("total", 0)
            cat_done  = counts.get("completed", 0)
            cat_pct   = (100 * cat_done // cat_total) if cat_total else 0
            print(f"  {cat:<22} {cat_done}/{cat_total} ({cat_pct}%)")


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def _get_sessions_dir(base_dir: str | None) -> Path:
    """Resolve .github/oboe_sessions using base_dir or CWD detection."""
    return oboe_sessions_dir(resolve_base_dir(base_dir))


def _get_session_file(session: str, base_dir: str | None) -> Path:
    """Resolve a session filename or path to an absolute Path."""
    sessions_dir = _get_sessions_dir(base_dir)
    return resolve_session_file(session, sessions_dir.parent.parent)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oboe-cli",
        description="Manage OBO (One-By-One) session files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Session directory resolution (--base-dir omitted):\n"
            "  1. CWD if it contains .github/oboe_sessions/\n"
            "  2. CWD as fallback\n"
        ),
    )
    parser.add_argument(
        "--session", "-s",
        metavar="SESSION",
        default=None,
        help=(
            "Session filename (e.g. session_20260411_120000.json) "
            "or absolute path"
        ),
    )
    parser.add_argument(
        "--base-dir", "-b",
        metavar="DIR",
        default=None,
        help="Project root for .github/oboe_sessions/ (overrides CWD detection)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- sessions -----------------------------------------------------------
    p = sub.add_parser("sessions", help="List all sessions")
    p.add_argument(
        "--status",
        choices=["active", "paused", "completed", "cancelled", "incomplete"],
        default=None,
        help="Filter by session status",
    )
    p.add_argument(
        "--active",
        action="store_true",
        default=False,
        help="Shorthand for --status active",
    )

    # --- status (session-level) ---------------------------------------------
    p = sub.add_parser("status", help="Show session summary statistics")
    p.add_argument(
        "--compact",
        action="store_true",
        default=False,
        help="One-line summary output",
    )

    # --- create -------------------------------------------------------------
    p = sub.add_parser("create", help="Create a new session")
    p.add_argument("--title",       default="", help="Session title")
    p.add_argument("--description", default="", help="Session description")
    _add_items_input(p)

    # --- merge --------------------------------------------------------------
    p = sub.add_parser("merge", help="Append new items to an existing session")
    _add_items_input(p)

    # --- complete-session ---------------------------------------------------
    sub.add_parser(
        "complete-session",
        help="Mark the entire session as completed",
    )

    # --- cancel-session -----------------------------------------------------
    p = sub.add_parser(
        "cancel-session",
        help="Mark a session as cancelled (abandoned/superseded)",
    )
    p.add_argument(
        "reason",
        nargs="*",
        help="Optional reason for cancellation",
    )

    # --- trim-sessions ------------------------------------------------------
    p = sub.add_parser(
        "trim-sessions",
        help="Delete session files by age and/or status",
    )
    p.add_argument(
        "--before",
        metavar="DATE",
        default=None,
        help=(
            "Delete sessions created before this date "
            "(ISO-8601, e.g. 2026-01-01, or 'now' to delete all matching)"
        ),
    )
    p.add_argument(
        "--status",
        dest="trim_status",
        choices=["active", "paused", "completed", "cancelled", "any"],
        default="completed",
        help=(
            "Only delete sessions with this status "
            "(default: completed; use 'any' to match all statuses)"
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be deleted without removing any files",
    )

    # --- list ---------------------------------------------------------------
    p = sub.add_parser("list", help="List items in the session")
    p.add_argument(
        "--status",
        choices=[
            "pending", "in_progress", "deferred",
            "blocked", "completed", "skipped",
        ],
        default=None,
        help="Filter by item status",
    )

    # --- next ---------------------------------------------------------------
    p = sub.add_parser("next", help="Show the next actionable item")
    p.add_argument(
        "--mark-in-progress",
        dest="mark_in_progress",
        action="store_true",
        default=False,
        help="Also mark the item in-progress",
    )

    # --- show ---------------------------------------------------------------
    p = sub.add_parser("show", help="Show full detail for one item")
    p.add_argument("item_id", help="Item ID")
    p.add_argument(
        "--fields",
        default=None,
        metavar="FIELDS",
        help="Comma-separated list of fields to display (e.g. id,title,status)",
    )

    # --- complete -----------------------------------------------------------
    p = sub.add_parser("complete", help="Mark an item as completed")
    p.add_argument("item_id", help="Item ID")
    p.add_argument(
        "--resolution",
        required=True,
        metavar="TEXT",
        help="Resolution description",
    )

    # --- skip ---------------------------------------------------------------
    p = sub.add_parser("skip", help="Mark an item as skipped")
    p.add_argument("item_id", help="Item ID")
    p.add_argument("reason", nargs="*", help="Optional reason for skipping")

    # --- in-progress --------------------------------------------------------
    p = sub.add_parser("in-progress", help="Mark an item as in progress")
    p.add_argument("item_id", help="Item ID")

    # --- block --------------------------------------------------------------
    p = sub.add_parser("block", help="Mark an item as blocked")
    p.add_argument("item_id", help="Item ID")
    p.add_argument("blocker", nargs="+", help="Blocker description")

    # --- approve ------------------------------------------------------------
    p = sub.add_parser("approve", help="Set approval metadata on an item")
    p.add_argument("item_id", help="Item ID")
    p.add_argument(
        "approval_status",
        choices=["approved", "denied", "unreviewed"],
        help="Approval decision",
    )
    p.add_argument(
        "--approval-mode",
        dest="approval_mode",
        choices=["immediate", "delayed"],
        default=None,
        help="Approval timing (only for approved)",
    )
    p.add_argument("--approval-note", dest="approval_note", default=None, help="Approval note")
    p.add_argument(
        "--lifecycle-status",
        dest="lifecycle_status",
        default=None,
        help="Also set the item lifecycle status",
    )

    # --- update -------------------------------------------------------------
    p = sub.add_parser("update", help="Update a single field on an item")
    p.add_argument("item_id", help="Item ID")
    p.add_argument("field",   help="Field name to update")
    p.add_argument("value",   help="New value")

    # --- create-child -------------------------------------------------------
    p = sub.add_parser(
        "create-child",
        help="Create a child session and pause the parent",
    )
    p.add_argument(
        "--parent-item-id",
        dest="parent_item_id",
        default=None,
        help="Parent item to block while child is active",
    )
    p.add_argument("--title",       default="", help="Child session title")
    p.add_argument("--description", default="", help="Child session description")
    p.add_argument(
        "--child-session",
        dest="child_session",
        default=None,
        metavar="CHILD_SESSION",
        help="Filename for the new child session (auto-generated if omitted)",
    )
    _add_items_input(p)

    # --- complete-child -----------------------------------------------------
    p = sub.add_parser(
        "complete-child",
        help="Close a child session and resume the parent",
    )
    p.add_argument(
        "resolution",
        nargs="*",
        help="Resolution summary stored on the unblocked parent item",
    )
    p.add_argument(
        "--disposition",
        choices=["completed", "cancelled"],
        default="completed",
        help="'completed' (default, all items must be done) or 'cancelled' (abandoned, open items allowed)",
    )

    return parser


def _add_items_input(parser: argparse.ArgumentParser) -> None:
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--items",
        metavar="JSON",
        help="Inline JSON array of items, or '-' to read from stdin",
    )
    grp.add_argument(
        "--input-file", "-i",
        metavar="FILE",
        help="Path to a JSON file containing the items list",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_items(input_file: str) -> list[dict]:
    path = Path(input_file)
    if not path.exists():
        print(f"❌ Input file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"❌ Invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list):
        print(f"❌ Expected a JSON array in {path}", file=sys.stderr)
        sys.exit(1)
    return data


def _resolve_items(args: argparse.Namespace) -> list[dict]:
    """Return items from --items inline JSON/stdin or --input-file."""
    if getattr(args, "items", None) is not None:
        raw = sys.stdin.read() if args.items == "-" else args.items
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"❌ Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(data, list):
            print("❌ Expected a JSON array", file=sys.stderr)
            sys.exit(1)
        return data
    return _read_items(args.input_file)


def _require_session(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    if args.session:
        return _get_session_file(args.session, args.base_dir)
    # Auto-infer: succeed only when exactly one active session exists
    sessions_dir = _get_sessions_dir(args.base_dir)
    if sessions_dir.exists():
        active = [
            r for r in list_sessions(sessions_dir)
            if r.get("status") not in {"completed", "cancelled"}
        ]
        if len(active) == 1:
            return sessions_dir / active[0]["file"]
        if len(active) > 1:
            names = ", ".join(r["file"] for r in active)
            parser.error(
                f"--session is required: multiple active sessions exist ({names})"
            )
    parser.error("--session is required for this command")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_sessions(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> int:
    sessions_dir = _get_sessions_dir(args.base_dir)
    if not sessions_dir.exists():
        print("No .github/oboe_sessions directory found.")
        return 0
    status_filter = "active" if getattr(args, "active", False) else getattr(args, "status", None)
    rows = list_sessions(sessions_dir, status_filter=status_filter)
    _print_sessions_table(rows)
    return 0


def _cmd_status(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf    = _require_session(args, parser)
    stats = session_status(sf)
    if getattr(args, "compact", False):
        total     = stats.get("total", 0)
        done      = stats.get("done", 0)
        pct       = stats.get("pct_done", (100 * done // total) if total else 0)
        in_prog   = stats.get("in_progress", 0)
        pending   = stats.get("pending", 0)
        blocked   = stats.get("blocked", 0)
        print(f"{done}/{total} done ({pct}%) — {in_prog} in-progress, {pending} pending, {blocked} blocked")
    else:
        _print_session_status(stats)
    return 0


def _cmd_create(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.session:
        # Auto-generate filename
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sf = _get_sessions_dir(args.base_dir) / f"session_{ts}.json"
    else:
        session_path = Path(args.session)
        try:
            validate_session_filename(session_path.name)
        except ValueError as exc:
            parser.error(str(exc))

        if session_path.is_absolute():
            sf = session_path
        else:
            sf = _get_sessions_dir(args.base_dir) / session_path.name

    items = _resolve_items(args)
    try:
        session = create_session(
            sf,
            items,
            title=args.title,
            description=args.description,
        )
    except FileExistsError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    print(f"✓ Session created: {sf.name}")
    print(f"✓ Items: {len(session['items'])}")
    return 0


def _cmd_merge(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf    = _require_session(args, parser)
    items = _resolve_items(args)
    try:
        result = merge_items(sf, items)
    except (ValueError, KeyError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    merged = result.get("merged_items", [])
    print(f"✓ {len(merged)} item(s) merged into: {sf.name}")
    print(f"✓ Total items now: {len(result['session']['items'])}")
    return 0


def _cmd_complete_session(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf = _require_session(args, parser)
    try:
        session = complete_session(sf)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    items     = session.get("items", [])
    total     = len(items)
    completed = sum(1 for i in items if i.get("status") == "completed")
    skipped   = sum(1 for i in items if i.get("status") == "skipped")
    print(f"✓ Session marked completed: {sf.name}")
    print(f"✓ Final: {completed} completed, {skipped} skipped, {total} total")
    return 0


def _cmd_cancel_session(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf     = _require_session(args, parser)
    reason = " ".join(args.reason) if args.reason else ""
    try:
        session = cancel_session(sf, reason)
    except (ValueError, OSError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    items = session.get("items", [])
    open_n = sum(
        1 for i in items if i.get("status") in {"pending", "in_progress", "deferred", "blocked"}
    )
    print(f"✓ Session marked cancelled: {sf.name}")
    if reason:
        print(f"  Reason: {reason}")
    if open_n:
        print(f"  Note: {open_n} item(s) left open")
    return 0


def _cmd_trim_sessions(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sessions_dir = _get_sessions_dir(args.base_dir)
    if not sessions_dir.exists():
        print("No .github/oboe_sessions directory found.")
        return 0

    trim_status = getattr(args, "trim_status", "completed")
    status_arg  = None if trim_status == "any" else trim_status

    try:
        result = trim_sessions(
            sessions_dir,
            before=args.before,
            status_filter=status_arg,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    prefix = "Would delete" if args.dry_run else "Deleted"
    n = result["total_deleted"]
    print(f"{'[DRY RUN] ' if args.dry_run else ''}{prefix} {n} session(s):")
    for name in result["deleted"]:
        print(f"  - {name}")
    if result["total_retained"]:
        print(f"Retained: {result['total_retained']} session(s)")
    return 0


def _cmd_list(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf    = _require_session(args, parser)
    items = list_items(sf, status_filter=getattr(args, "status", None))
    _print_items_table(items)
    return 0


def _cmd_next(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf   = _require_session(args, parser)
    try:
        item = get_next(sf)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    if getattr(args, "mark_in_progress", False):
        try:
            mark_in_progress(sf, item["id"])
        except (KeyError, ValueError) as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 1
    stats = session_status(sf)
    _print_next(item, stats)
    return 0


def _cmd_show(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf   = _require_session(args, parser)
    item = get_item(sf, args.item_id)
    if item is None:
        print(f"❌ Item {args.item_id} not found", file=sys.stderr)
        return 1
    fields_arg = getattr(args, "fields", None)
    if fields_arg:
        field_list = [f.strip() for f in fields_arg.split(",") if f.strip()]
        item = {k: v for k, v in item.items() if k in field_list}
    _print_item_detail(item)
    return 0


def _cmd_complete(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf = _require_session(args, parser)
    resolution = args.resolution
    try:
        session  = mark_complete(sf, args.item_id, resolution)
    except KeyError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    items     = session.get("items", [])
    completed = sum(1 for i in items if i.get("status") == "completed")
    total     = len(items)
    print(f"✓ Item {args.item_id} marked completed")
    print(f"✓ Progress: {completed}/{total} items completed")
    return 0


def _cmd_skip(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf     = _require_session(args, parser)
    reason = " ".join(args.reason) if args.reason else ""
    try:
        session = mark_skip(sf, args.item_id, reason)
    except KeyError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    skipped = sum(1 for i in session.get("items", []) if i.get("status") == "skipped")
    print(f"✓ Item {args.item_id} marked skipped")
    if reason:
        print(f"  Reason: {reason}")
    print(f"✓ Total skipped: {skipped}")
    return 0


def _cmd_in_progress(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf = _require_session(args, parser)
    try:
        session = mark_in_progress(sf, args.item_id)
    except KeyError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    in_prog = sum(1 for i in session.get("items", []) if i.get("status") == "in_progress")
    print(f"✓ Item {args.item_id} marked in progress")
    print(f"✓ Total in progress: {in_prog}")
    return 0


def _cmd_block(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf      = _require_session(args, parser)
    blocker = " ".join(args.blocker)
    try:
        mark_blocked(sf, args.item_id, blocker)
    except KeyError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    print(f"✓ Item {args.item_id} marked blocked")
    print(f"  Blocker: {blocker}")
    return 0


def _cmd_approve(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf = _require_session(args, parser)
    try:
        item = set_approval(
            sf,
            args.item_id,
            args.approval_status,
            approval_mode=args.approval_mode,
            note=args.approval_note,
            lifecycle_status=args.lifecycle_status,
        )
    except (KeyError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    print(f"✓ Item {args.item_id} approval_status={item['approval_status']}")
    if item.get("approval_mode"):
        print(f"  Mode: {item['approval_mode']}")
    if item.get("approval_note"):
        print(f"  Note: {item['approval_note']}")
    return 0


def _cmd_update(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf = _require_session(args, parser)
    try:
        item = update_field(sf, args.item_id, args.field, args.value)
    except (KeyError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    score = item.get("priority_score", "")
    if args.field in {"urgency", "importance", "effort", "dependencies"}:
        print(
            f"✓ Item {args.item_id}: {args.field} = {args.value} "
            f" →  priority_score recalculated = {score}"
        )
    else:
        print(f"✓ Item {args.item_id}: {args.field} = {args.value}")
    return 0


def _cmd_create_child(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    parent_sf    = _require_session(args, parser)
    sessions_dir = _get_sessions_dir(args.base_dir)
    if args.child_session is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        child_sf = sessions_dir / f"session_{ts}.json"
    else:
        child_name = Path(args.child_session).name
        try:
            validate_session_filename(child_name)
        except ValueError as exc:
            parser.error(str(exc))
        child_sf = sessions_dir / child_name
    items    = _resolve_items(args)
    try:
        result = create_child_session(
            parent_sf,
            child_sf,
            items,
            title=args.title,
            description=args.description,
            parent_item_id=args.parent_item_id,
        )
    except (FileExistsError, ValueError, KeyError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    child = result["child_session"]
    print(f"✓ Child session created: {child_sf.name}")
    print(f"✓ Items: {len(child['items'])}")
    print(f"✓ Parent session paused: {parent_sf.name}")
    return 0


def _cmd_complete_child(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sf          = _require_session(args, parser)
    resolution  = " ".join(args.resolution) if args.resolution else ""
    disposition = getattr(args, "disposition", "completed")
    try:
        result = complete_child_session(sf, resolution, disposition=disposition)
    except ValueError as exc:
        print(f"\u274c {exc}", file=sys.stderr)
        return 1
    parent = result["parent_session"]
    child  = result["child_session"]
    parent_items = parent.get("items", [])
    total = len(parent_items)
    done = sum(1 for i in parent_items if i.get("status") in {"completed", "skipped"})
    pct_done = (done / total * 100.0) if total else 0.0
    verb = disposition  # "completed" or "cancelled"
    print(f"\u2713 Child session {verb}: {sf.name}")
    print(f"✓ Parent session resumed: {child.get('parent_session_file', '')}")
    _print_session_status(
        {
            "session_file": parent.get("session_file", ""),
            "total": total,
            "completed": sum(1 for i in parent_items if i.get("status") == "completed"),
            "skipped": sum(1 for i in parent_items if i.get("status") == "skipped"),
            "in_progress": sum(1 for i in parent_items if i.get("status") == "in_progress"),
            "pending": sum(1 for i in parent_items if i.get("status") == "pending"),
            "deferred": sum(1 for i in parent_items if i.get("status") == "deferred"),
            "blocked": sum(1 for i in parent_items if i.get("status") == "blocked"),
            "done": done,
            "pct_done": pct_done,
            "categories": {},
        }
    )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_COMMAND_DISPATCH = {
    "sessions":        _cmd_sessions,
    "status":          _cmd_status,
    "create":          _cmd_create,
    "merge":           _cmd_merge,
    "complete-session": _cmd_complete_session,
    "list":            _cmd_list,
    "next":            _cmd_next,
    "show":            _cmd_show,
    "complete":        _cmd_complete,
    "skip":            _cmd_skip,
    "in-progress":     _cmd_in_progress,
    "block":           _cmd_block,
    "approve":         _cmd_approve,
    "update":          _cmd_update,
    "create-child":    _cmd_create_child,
    "complete-child":  _cmd_complete_child,
    "cancel-session":  _cmd_cancel_session,
    "trim-sessions":   _cmd_trim_sessions,
}

def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args   = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    handler = _COMMAND_DISPATCH.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args, parser)
    except FileNotFoundError as exc:
        fname = exc.filename or str(exc)
        print(f"❌ Session file not found: {fname}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
