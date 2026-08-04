# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
OBO Session business logic — ported from oboe_helper.py.

All public functions operate on Path objects or string paths.
session_file parameters accept an absolute path or a filename
relative to {base_dir}/.github/oboe_sessions/.
"""

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from .locking import atomic_write_json, sessions_lock

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
# Ordered for deterministic error reporting; _SCORE_COMPONENTS stays a set
# because the rest of the module uses it for membership tests only.
_SCORE_COMPONENT_ORDER = ("urgency", "importance", "effort", "dependencies")
_SCORE_COMPONENTS = set(_SCORE_COMPONENT_ORDER)
_SCORE_MIN = 0
_SCORE_MAX = 5
# Fields `update_field` may set.  Deliberately an allow-list, not a denylist:
# a session file is a documented schema, and an unrecognised field name is far
# more likely a typo or a hallucinated field than a deliberate extension.
# `id` is absent on purpose — see update_field.
_UPDATABLE_FIELDS = {
    "title",
    "category",
    "description",
    "status",
    "resolution",
    "skip_reason",
    "blocker",
    "blocked_at",
    "approval_status",
    "approval_mode",
    "approved_at",
    "approval_note",
    "child_session_resolution",
    "priority_score",
} | _SCORE_COMPONENTS
_SESSION_RE = re.compile(r"^session_\d{8}_\d{6}\.json$")
_VALID_SESSION_STATUSES = {"active", "paused", "completed", "cancelled"}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def oboe_sessions_dir(base_dir: str | Path) -> Path:
    """Return the .github/oboe_sessions directory for a given base dir.
    If base_dir already ends with .github/oboe_sessions, return as-is.
    """
    p = Path(base_dir).resolve()
    if p.name == "oboe_sessions" and p.parent.name == ".github":
        return p
    return p / ".github" / "oboe_sessions"


def resolve_base_dir(base_dir: str | Path | None = None) -> Path:
    """Resolve the project base directory for CLI use.

    Priority:
      1. *base_dir* if supplied (converted to an absolute path)
      2. CWD if it contains ``.github/oboe_sessions/``
      3. CWD as a fallback (directory may not yet exist)
    """
    if base_dir is not None:
        return Path(base_dir).resolve()
    cwd = Path.cwd()
    if (cwd / ".github" / "oboe_sessions").exists():
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
    - A bare filename → resolved relative to base_dir/.github/oboe_sessions/
    """
    p = Path(session_file)
    if p.is_absolute():
        return p.resolve()
    if base_dir is not None:
        return (oboe_sessions_dir(base_dir) / p).resolve()
    # Caller must pass an absolute path if base_dir is None
    raise ValueError(
        f"session_file '{session_file}' is relative but no base_dir "
        "was provided"
    )


# ---------------------------------------------------------------------------
# Low-level I/O
# ---------------------------------------------------------------------------

def load_session(session_file: Path) -> dict:
    """Read a session file.

    Callers that will subsequently write must hold the exclusive lock across
    the whole read-modify-write cycle — use :func:`session_transaction` rather
    than pairing this with :func:`save_session` by hand.  Called on its own it
    takes a shared lock, so it never observes a partially-written file.
    """
    session_file = Path(session_file)
    with sessions_lock(session_file.parent, exclusive=False):
        return _load_session_unlocked(session_file)


def _load_session_unlocked(session_file: Path) -> dict:
    """Read a session file assuming the caller already holds the lock."""
    with open(session_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(session_file: Path, session: dict) -> None:
    """Write a session file atomically.

    Kept for callers that manage their own locking; the write itself is atomic
    either way, so a concurrent reader never sees a truncated file.
    """
    session_file = Path(session_file)
    with sessions_lock(session_file.parent, exclusive=True):
        atomic_write_json(session_file, session)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@contextmanager
def session_transaction(session_file: Path):
    """Hold the sessions-directory lock across a read-modify-write cycle.

    Loads and normalizes the session, yields it for mutation, then writes the
    session file and updates ``index.json`` — all under one exclusive lock, so
    the pair cannot be observed or interleaved half-applied.

    The session status is *not* synced automatically; callers that need
    :func:`_sync_session_status` call it before the block exits, matching the
    previous hand-written ordering.

    Raises:
        LockBusy / LockTimeout: per the active lock policy.
    """
    session_file = Path(session_file)
    with sessions_lock(session_file.parent, exclusive=True):
        session = _load_session_unlocked(session_file)
        _normalize_existing_items(session)
        yield session
        _write_session_and_index(session_file, session)


def _write_session_and_index(session_file: Path, session: dict) -> None:
    """Commit a session plus its index row.  Caller must hold the lock."""
    atomic_write_json(session_file, session)
    _upsert_index(session_file.parent, session, session_file.name)


# ---------------------------------------------------------------------------
# Priority score
# ---------------------------------------------------------------------------

def _score_error(
    item_id: object,
    field: str,
    value: object,
    detail: str = "",
) -> ValueError:
    """Build the rejection message for a bad score component.

    The message names the item *and* the field, because the caller supplies a
    whole batch of items and the bare arithmetic error named neither.
    """
    suffix = detail or f"got {type(value).__name__}: {value!r}"
    return ValueError(
        f"item {item_id!r}: {field!r} must be a number "
        f"{_SCORE_MIN}-{_SCORE_MAX} ({suffix})"
    )


def _as_score_int(value: object) -> int | None:
    """Return *value* as an int if it is an integral real number, else None.

    ``bool`` is rejected despite being an ``int`` subclass: ``True`` as an
    urgency is a type error the caller wants to hear about, not a 1.  A float
    is accepted only when integral, since JSON has no int/float distinction and
    ``3.0`` is a legitimate way to write 3 — but ``2.5`` is not a score.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not isfinite(value) or not value.is_integer():
            return None
        return int(value)
    return None


def _score_value(item: dict, field: str, default: int) -> int:
    """Read one score component for the arithmetic, or raise a clear error.

    This is the *inner* of the two validation layers.  Boundary callers have
    already validated their input via :func:`validate_score_components`; this
    guard exists so that no route into the arithmetic — including loading a
    session file written by an older version, or by hand — can produce a bare
    ``TypeError`` naming neither item nor field.

    It deliberately checks type only, not range: nothing has ever bounded these
    values on disk, so enforcing the range here would make a previously
    readable session file unloadable.
    """
    value = item.get(field, default)
    number = _as_score_int(value)
    if number is None:
        raise _score_error(item.get("id"), field, value)
    return number


def validate_score_components(item: dict, item_id: object = None) -> dict:
    """Validate and normalize caller-supplied score components, in place.

    This is the *outer* layer, applied at the input boundary to items that
    arrived from an MCP client, the CLI, or another caller — where the values
    are LLM-generated JSON and cannot be assumed well-formed.  Unlike
    :func:`_score_value` it also enforces the documented 0-5 range, and it
    rejects a component that is present but ``None``.

    Absent components are left absent; :func:`_normalize_item` supplies the
    defaults.

    Args:
        item: Raw item dict; validated components are replaced with ints.
        item_id: Identifier to name in errors. Defaults to ``item["id"]``.

    Returns:
        The same dict, for convenient chaining.

    Raises:
        ValueError: naming the item and the field, for any bad component.
    """
    if item_id is None:
        item_id = item.get("id")
    for field in _SCORE_COMPONENT_ORDER:
        if field not in item:
            continue
        value = item[field]
        number = _as_score_int(value)
        if number is None:
            raise _score_error(item_id, field, value)
        if not _SCORE_MIN <= number <= _SCORE_MAX:
            raise _score_error(item_id, field, value, detail=f"got {number}")
        item[field] = number
    return item


def validate_item_id(item_id: object) -> str | int:
    """Validate a caller-supplied item id.

    ``id`` is documented as "string or integer".  Anything else reaches
    :func:`_id_sort_key`, ``str()``-based lookup and the duplicate check as an
    unconstrained value, so it is rejected at the boundary rather than stored.

    ``None`` is rejected rather than silently read as "assign one for me":
    ``setdefault`` does not replace an explicit ``None``, so it would have
    become a real item id of ``None``, matched by the string ``"None"``.
    """
    if isinstance(item_id, bool) or item_id is None:
        raise ValueError(
            "Item 'id' must be a string or an integer "
            f"(got {type(item_id).__name__}: {item_id!r}). "
            "Omit the field entirely to have one assigned."
        )
    if isinstance(item_id, int):
        return item_id
    if isinstance(item_id, str):
        if not item_id.strip():
            raise ValueError("Item 'id' must not be blank")
        return item_id
    raise ValueError(
        "Item 'id' must be a string or an integer "
        f"(got {type(item_id).__name__}: {item_id!r})"
    )


def _stage_items(
    items: list[dict],
    taken: set[str] | None = None,
    start: int = 1,
) -> list[dict]:
    """Validate a batch of caller-supplied items and settle their ids.

    Runs before any lock is taken and before anything is written, so a batch
    that fails validation leaves no session file, no directory and no
    partially-appended items.

    Explicit ids are validated and checked for duplicates — against each other
    *and* against *taken*, the ids already in the session.  Items with no id
    are assigned the lowest free integer, skipping ids the batch has claimed.

    Both :func:`create_session` and :func:`merge_items` use this.  They used to
    differ: ``merge_items`` rejected duplicates while ``create_session``
    accepted them, and a duplicate id makes the second item permanently
    unreachable — every lookup resolves to the first — so ``oboe_next`` could
    hand back an item and then mark a *different* one in progress.

    Args:
        items: Raw item dicts from the caller.
        taken: String forms of ids already present in the session.
        start: Lowest integer to consider when auto-assigning. ``merge_items``
            passes one past the highest existing id so an appended item never
            reuses a number that already appeared in this session's history.

    Returns:
        Fresh copies, with score components normalized and ``id`` set.

    Raises:
        ValueError: for a bad score component, a bad id, or a duplicate id.
    """
    if not isinstance(items, list):
        raise ValueError(
            f"'items' must be a list of objects, got {type(items).__name__}"
        )

    claimed = set(taken or ())
    staged: list[dict] = []

    # First pass: validate everything the caller stated explicitly, so a
    # duplicate is reported against the id the caller actually wrote.
    for position, raw_item in enumerate(items, start=1):
        # Check the container before copying it.  `dict(raw_item)` on a string
        # or None reports in the interpreter's vocabulary ("dictionary update
        # sequence element #0 has length 1") rather than saying which item of
        # the batch is the wrong shape.
        if not isinstance(raw_item, dict):
            raise ValueError(
                f"item #{position} must be an object, got "
                f"{type(raw_item).__name__}: {raw_item!r}"
            )
        item = dict(raw_item)
        if "id" in item:
            item["id"] = validate_item_id(item["id"])
            key = str(item["id"])
            if key in claimed:
                raise ValueError(f"Duplicate item id: {item['id']}")
            claimed.add(key)
        validate_score_components(item, item.get("id", f"#{position}"))
        staged.append(item)

    # Second pass: fill in the gaps.  Deferring this until every explicit id is
    # known is what stops an auto-assigned id from colliding with one stated
    # later in the same batch.
    next_idx = start
    for item in staged:
        if "id" in item:
            continue
        while str(next_idx) in claimed:
            next_idx += 1
        item["id"] = next_idx
        claimed.add(str(next_idx))
        next_idx += 1

    return staged


def _validate_score_string(item_id: object, field: str, value: object) -> int:
    """Validate a score component that arrived over a stringly-typed channel.

    ``oboe_update_field`` declares ``value: str`` and the CLI reads it from
    ``argv``, so a numeric string is the *normal* input there and is parsed
    rather than rejected — unlike :func:`validate_score_components`, whose
    callers receive JSON and can declare these fields as numbers.
    """
    candidate: object = value
    if isinstance(value, str):
        try:
            candidate = int(value.strip())
        except ValueError:
            try:
                candidate = float(value.strip())
            except ValueError:
                raise _score_error(item_id, field, value) from None
    number = _as_score_int(candidate)
    if number is None:
        raise _score_error(item_id, field, value)
    if not _SCORE_MIN <= number <= _SCORE_MAX:
        raise _score_error(item_id, field, value, detail=f"got {number}")
    return number


def _recalc_priority(item: dict) -> int:
    """Recalculate priority_score from component fields in place.

    Raises:
        ValueError: if any component is non-numeric, naming item and field.
    """
    item["priority_score"] = (
        _score_value(item, "urgency", 3)
        + _score_value(item, "importance", 3)
        + (6 - _score_value(item, "effort", 3))
        + _score_value(item, "dependencies", 1)
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
    """Read index.json, taking a shared lock unless one is already held."""
    with sessions_lock(sessions_dir, exclusive=False):
        return _load_index_unlocked(sessions_dir)


def _load_index_unlocked(sessions_dir: Path) -> dict:
    idx_path = _index_path(sessions_dir)
    if idx_path.exists():
        with open(idx_path, encoding="utf-8") as f:
            return json.load(f)
    return {"format_version": 1, "last_updated": "", "sessions": []}


def _save_index(sessions_dir: Path, index: dict) -> None:
    """Write index.json atomically.  Caller is expected to hold the lock."""
    index["last_updated"] = datetime.now().isoformat()
    atomic_write_json(_index_path(sessions_dir), index)


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
    """Keep the session-level status in sync with item states.

    A 'cancelled' session retains that status regardless of item states.
    """
    if session.get("status") == "cancelled":
        return "cancelled"
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
    """Scan all session_*.json files and return a fresh index dict.

    Caller must hold the sessions lock; the scan reads every session file and
    would otherwise produce a mixed-time snapshot under concurrent writes.
    """
    rows = []
    for sf in sorted(sessions_dir.glob("session_*.json")):
        try:
            s = _load_session_unlocked(sf)
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

    Caller must hold the exclusive sessions lock — this is a read-modify-write
    on index.json and is always paired with a session-file write.
    """
    try:
        index = _load_index_unlocked(sessions_dir)
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


def reindex(sessions_dir: Path | str, *, write: bool = True) -> dict:
    """Rebuild ``index.json`` unconditionally from the session files on disk.

    Every other index repair in this module is *conditional*: it fires only when
    the index is missing, corrupt, or structurally invalid (see ``_upsert_index``
    and ``list_sessions``).  That leaves one failure mode uncovered — an index
    that is perfectly **valid** but no longer **complete**.  A valid-but-stale
    index is indistinguishable from a correct one to every existing code path, so
    nothing repairs it and nothing reports it.

    That is not hypothetical.  It was found in ``agent-config`` on 2026-07-31: a
    tracked ``index.json`` was reverted to an older committed revision, leaving it
    listing **1 session while 12 existed on disk**.  ``_is_valid_index`` returned
    True — ``format_version`` was 1 and ``sessions`` was a list — so
    ``list_sessions`` took the fast path and reported the single stale row.  The
    other 11 sessions, including an in-flight one, were invisible to every tool
    while their files sat intact in the same directory.

    This function is the deliberate escape hatch: it ignores the current index
    entirely and regenerates it from the files, which are the actual source of
    truth.  It reports what changed rather than repairing silently, so drift is
    visible after the fact instead of merely gone.

    With ``write=False`` the rebuild is computed and compared but **not saved**,
    which backs a ``--check`` mode for CI or a pre-commit hook.  The comparison
    still happens under a lock, so a concurrent write cannot make the report a
    blend of two states.

    An index that is already correct is **not rewritten**: ``_save_index`` stamps
    ``last_updated``, so an unconditional write would turn every no-op run into a
    one-line diff, and in a versioned session store that is churn on a command
    meant to be safe to run whenever the list looks wrong.  A *corrupt* index is
    always rewritten even when the rebuilt rows happen to match, or the bad bytes
    would survive a repair that reported success.

    Returns a summary dict with ``added``/``removed``/``updated`` filename lists,
    the before/after entry counts, ``changed`` (False when the index was already
    accurate — the common case, and worth being able to assert), and ``written``
    (what actually happened, which ``write=True`` no longer implies).
    """
    sessions_dir = Path(sessions_dir)

    # A read-only check needs only the shared lock; a rebuild mutates and needs
    # the exclusive one.
    with sessions_lock(sessions_dir, exclusive=write):
        # Track whether the existing index was USABLE, separately from whether
        # its contents match.  A corrupt index whose rebuild happens to produce
        # the same (e.g. empty) row set is "unchanged" by row comparison and
        # still needs rewriting — otherwise the corrupt bytes survive a repair
        # that reported success.
        old_index_ok = False
        try:
            old = _load_index_unlocked(sessions_dir)
            if _is_valid_index(old):
                old_rows = old["sessions"]
                old_index_ok = True
            else:
                old_rows = []
        except (json.JSONDecodeError, ValueError, OSError):
            # Unreadable or corrupt: treat as empty rather than failing.  The
            # whole point of this call is to recover from a bad index.
            old_rows = []

        rebuilt = _rebuild_index_from_files(sessions_dir)
        new_rows = rebuilt["sessions"]

        # Guard the key type, not just the row type.  A row whose "file" is
        # missing or non-str would put None into these sets, and the sorted()
        # calls below raise TypeError on None — crashing the one function whose
        # job is to recover from a malformed index.  Such rows are dropped:
        # they name no file, so they cannot correspond to anything on disk.
        old_by_file = {
            r["file"]: r
            for r in old_rows
            if isinstance(r, dict) and isinstance(r.get("file"), str)
        }
        new_by_file = {r["file"]: r for r in new_rows}

        added = sorted(set(new_by_file) - set(old_by_file))
        removed = sorted(set(old_by_file) - set(new_by_file))
        updated = sorted(
            f for f in set(old_by_file) & set(new_by_file)
            if old_by_file[f] != new_by_file[f]
        )

        changed = bool(added or removed or updated)

        # Do not rewrite an index that is already correct.  `_save_index` stamps
        # `last_updated`, so an unconditional write turns every no-op run into a
        # one-line diff — which in a versioned session store (the canonical
        # layout) means spurious churn on a command whose whole purpose is to be
        # safe to run whenever the list looks wrong.
        written = bool(write and (changed or not old_index_ok))
        if written:
            _save_index(sessions_dir, rebuilt)

    unreadable = sorted(
        r["file"] for r in new_rows if r.get("status") == "unreadable"
    )
    return {
        "sessions_dir": str(sessions_dir),
        # What actually happened, not what was requested — a caller asserting on
        # this needs the outcome, and `write=True` no longer implies a write.
        "written": written,
        "before": len(old_rows),
        "after": len(new_rows),
        "added": added,
        "removed": removed,
        "updated": updated,
        "unreadable": unreadable,
        "changed": changed,
    }


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

    The existence check and the write happen under one exclusive lock, so two
    processes cannot both pass the check and race to create the same file.

    Raises FileExistsError if the session file already exists.
    """
    validate_session_filename(session_file.name)

    # Validate before taking the lock or creating anything: a bad batch must
    # not leave a directory or a half-written session behind.
    staged = _stage_items(items)

    session_file.parent.mkdir(parents=True, exist_ok=True)

    with sessions_lock(session_file.parent, exclusive=True):
        if session_file.exists():
            raise FileExistsError(
                f"Session file already exists: {session_file}"
            )

        normalized = [
            _normalize_item(item, item["id"]) for item in staged
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
        _write_session_and_index(session_file, session)
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
    with sessions_lock(sessions_dir, exclusive=False):
        if idx_path.exists():
            try:
                index = _load_index_unlocked(sessions_dir)
                if _is_valid_index(index):
                    rows = index["sessions"]
            except (json.JSONDecodeError, ValueError):
                rows = None  # corrupt index – fall through to rebuild

    if rows is None:
        # Slow path: scan files and repair the index.  This writes, so it
        # needs the exclusive lock rather than the reader lock above.
        with sessions_lock(sessions_dir, exclusive=True):
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
    elif status_filter == "cancelled":
        rows = [r for r in rows if r.get("status") == "cancelled"]
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
    with session_transaction(session_file) as session:
        item = _require_item(session, item_id)
        item["status"] = "completed"
        item["resolution"] = resolution
        _clear_blocker_fields(item)
        _sync_session_status(session)
    return session


def mark_skip(
    session_file: Path,
    item_id: str | int,
    reason: str = "",
) -> dict:
    """Mark an item skipped. Returns updated session."""
    with session_transaction(session_file) as session:
        item = _require_item(session, item_id)
        item["status"] = "skipped"
        if reason:
            item["skip_reason"] = reason
        _clear_blocker_fields(item)
        _sync_session_status(session)
    return session


def mark_deferred(
    session_file: Path,
    item_id: str | int,
    reason: str = "",
    deferred_until: str = "",
) -> dict:
    """Mark an item deferred. Returns updated item dict."""
    with session_transaction(session_file) as session:
        item = _require_item(session, item_id)
        item["status"] = "deferred"
        if reason:
            item["defer_reason"] = reason
        if deferred_until:
            item["deferred_until"] = deferred_until
        _clear_blocker_fields(item)
        _sync_session_status(session)
    return item


def mark_blocked(
    session_file: Path,
    item_id: str | int,
    blocker: str | dict,
) -> dict:
    """Mark an item blocked and store blocker metadata."""
    with session_transaction(session_file) as session:
        item = _require_item(session, item_id)
        item["status"] = "blocked"
        item["blocker"] = _blocker_payload(blocker)
        item["blocked_at"] = datetime.now().isoformat()
        _sync_session_status(session)
    return session


def mark_in_progress(session_file: Path, item_id: str | int) -> dict:
    """Mark an item in progress. Returns updated session."""
    with session_transaction(session_file) as session:
        item = _require_item(session, item_id)
        item["status"] = "in_progress"
        _clear_blocker_fields(item)
        _sync_session_status(session)
    return session


def complete_session(session_file: Path) -> dict:
    """Mark the session completed when no actionable items remain."""
    with session_transaction(session_file) as session:
        if _open_count(session) > 0:
            raise ValueError(
                "Cannot complete session while pending, in_progress, "
                "deferred, or blocked "
                "items remain"
            )
        session["status"] = "completed"
        session.setdefault("completed_at", datetime.now().isoformat())
    return session


def cancel_session(session_file: Path, reason: str = "") -> dict:
    """Mark a session cancelled (abandoned/superseded, not completed).

    Unlike ``complete_session``, open items are allowed — the session is
    simply marked as no longer being worked.
    """
    with session_transaction(session_file) as session:
        session["status"] = "cancelled"
        session["cancelled_at"] = datetime.now().isoformat()
        if reason:
            session["cancel_reason"] = reason
    return session


def trim_sessions(
    sessions_dir: Path,
    before: datetime | str | None = None,
    status_filter: str | None = "completed",
    dry_run: bool = False,
) -> dict:
    """Delete session files matching *status_filter* and/or created before *before*.

    Args:
        sessions_dir: The ``.github/oboe_sessions`` directory.
        before: Delete sessions created before this datetime.  Accepts a
            ``datetime`` object or an ISO-8601 string.  Pass ``datetime.now()``
            (or ``"now"``) to delete all sessions matching the status filter.
        status_filter: Only delete sessions with this status.  Pass ``None``
            to match any status.  Default is ``"completed"``.
        dry_run: If True, return what *would* be deleted without touching any
            files.

    Returns:
        A dict with keys ``deleted`` (list of filenames removed) and
        ``retained`` (list of filenames kept), plus ``dry_run`` bool.

    Raises:
        ValueError: if *before* is not parseable as a datetime.
    """
    sessions_dir = Path(sessions_dir)

    # Resolve the cutoff datetime
    cutoff: datetime | None = None
    if before is not None:
        if isinstance(before, str):
            if before.strip().lower() == "now":
                cutoff = datetime.now()
            else:
                try:
                    cutoff = datetime.fromisoformat(before)
                except ValueError:
                    raise ValueError(
                        f"Cannot parse 'before' as a date/datetime: {before!r}. "
                        "Use ISO-8601 format (e.g. '2026-04-01' or "
                        "'2026-04-01T12:00:00') or 'now'."
                    )
        else:
            cutoff = before

    # Deciding what to delete and deleting it must be one atomic step: the
    # decision is made from the index, and a concurrent mutation between the
    # two would shift the ground under it.
    with sessions_lock(sessions_dir, exclusive=True):
        rows = list_sessions(sessions_dir)
        deleted: list[str] = []
        retained: list[str] = []

        for row in rows:
            filename = row.get("file", "")
            status   = row.get("status", "")
            created  = row.get("created", "")  # YYYY-MM-DD or ISO string

            # Status filter
            if status_filter is not None and status != status_filter:
                retained.append(filename)
                continue

            # Age filter
            if cutoff is not None and created:
                try:
                    created_dt = datetime.fromisoformat(created[:10])  # date portion
                except ValueError:
                    retained.append(filename)
                    continue
                if created_dt > cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
                    retained.append(filename)
                    continue

            deleted.append(filename)

        if not dry_run:
            for filename in deleted:
                sf = sessions_dir / filename
                try:
                    sf.unlink(missing_ok=True)
                except OSError:
                    pass
            # Rebuild index from surviving files
            rebuilt = _rebuild_index_from_files(sessions_dir)
            _save_index(sessions_dir, rebuilt)

    return {
        "deleted":  deleted,
        "retained": retained,
        "dry_run":  dry_run,
        "total_deleted":  len(deleted),
        "total_retained": len(retained),
    }


def create_child_session(
    parent_session_file: Path,
    child_session_file: Path,
    items: list[dict],
    title: str = "",
    description: str = "",
    parent_item_id: str | int | None = None,
) -> dict:
    """Create a child session, pause the parent, and optionally block an item.

    Creating the child and pausing the parent happen under a single exclusive
    lock, so no other process can observe a child that exists while its parent
    still looks unpaused.  The nested :func:`create_session` re-enters the same
    lock rather than taking a second one.
    """
    with sessions_lock(parent_session_file.parent, exclusive=True):
        parent_session = _load_session_unlocked(parent_session_file)
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
            parent_session["child_session_files"].append(
                child_session_file.name
            )
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
        _write_session_and_index(parent_session_file, parent_session)

    return {
        "parent_session": parent_session,
        "child_session": child_session,
    }


def complete_child_session(
    child_session_file: Path,
    resolution: str = "",
    disposition: str = "completed",
) -> dict:
    """Close a child session and resume its parent session.

    Args:
        child_session_file: Path to the child session JSON.
        resolution: Optional note stored on the unblocked parent item.
        disposition: How the child is closed — ``"completed"`` (all items must
            be done; default) or ``"cancelled"`` (abandoned; open items are
            allowed).  In both cases the parent item is unblocked.

    Raises:
        ValueError: if *disposition* is not ``"completed"`` or ``"cancelled"``.
        ValueError: if *disposition* is ``"completed"`` and open items remain.
        ValueError: if the session has no ``parent_session_file`` field.
    """
    if disposition not in ("completed", "cancelled"):
        raise ValueError(
            f"Invalid disposition {disposition!r}. "
            "Must be 'completed' or 'cancelled'."
        )

    # Closing the child and resuming the parent are one atomic step.  Held
    # across both, so no other process can see a closed child whose parent is
    # still paused on it.  The nested complete_session/cancel_session
    # re-enter this same lock.
    with sessions_lock(child_session_file.parent, exclusive=True):
        if disposition == "completed":
            child_session = complete_session(child_session_file)
        else:  # cancelled
            child_session = cancel_session(child_session_file, reason=resolution)

        parent_session_name = child_session.get("parent_session_file")
        if not parent_session_name:
            raise ValueError("Session is not a child session")

        parent_session_file = child_session_file.parent / parent_session_name
        parent_session = _load_session_unlocked(parent_session_file)
        _normalize_existing_items(parent_session)
        if (
            parent_session.get("active_child_session")
            == child_session_file.name
        ):
            parent_session["active_child_session"] = None

        parent_item_id = child_session.get("parent_item_id")
        if parent_item_id is not None:
            parent_item = _require_item(parent_session, parent_item_id)
            blocker = parent_item.get("blocker") or {}
            if blocker.get("session_file") == child_session_file.name:
                parent_item["status"] = "pending"
                _clear_blocker_fields(parent_item)
                note = resolution if resolution else (
                    "Child session was cancelled."
                    if disposition == "cancelled" else ""
                )
                if note:
                    parent_item["child_session_resolution"] = note

        _sync_session_status(parent_session)
        _write_session_and_index(parent_session_file, parent_session)

    return {
        "child_session": child_session,
        "parent_session": parent_session,
    }


def merge_items(session_file: Path, items: list[dict]) -> dict:
    """Append items to an existing session and reactivate it if needed."""
    with session_transaction(session_file) as session:
        existing_ids = {
            str(item.get("id")) for item in session.get("items", [])
        }
        numeric_ids = [
            int(item_id) for item_id in existing_ids if item_id.isdigit()
        ]

        # Validate and settle the whole batch first.  Raising here propagates
        # out of session_transaction before its write, so a rejected merge
        # appends nothing.
        staged = _stage_items(
            items, taken=existing_ids, start=max(numeric_ids, default=0) + 1
        )

        merged_items = []
        for item in staged:
            normalized = _normalize_item(item, item["id"])
            session.setdefault("items", []).append(normalized)
            merged_items.append(normalized)

        _sync_session_status(session)
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
    with session_transaction(session_file) as session:
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
    return item


def update_field(
    session_file: Path,
    item_id: str | int,
    field: str,
    value: str | int,
) -> dict:
    """Update a field on an item, auto-recalculating priority_score if needed.

    Only fields in the documented item schema may be set (see
    ``_UPDATABLE_FIELDS``); the store is not a free-form bag.  ``id`` is
    excluded outright — rewriting it into a collision makes an item permanently
    unreachable, because every lookup then resolves to the other one.

    Returns the updated item dict.

    Raises:
        KeyError: no such item.
        ValueError: unknown field, or a value the field rejects.
    """
    if field not in _UPDATABLE_FIELDS:
        if field == "id":
            raise ValueError(
                "'id' cannot be changed. An id collision makes one of the two "
                "items unreachable, since every lookup resolves to the first."
            )
        raise ValueError(
            f"Unknown item field: {field!r}. Updatable fields are: "
            f"{', '.join(sorted(_UPDATABLE_FIELDS))}"
        )

    with session_transaction(session_file) as session:
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
        if field in _SCORE_COMPONENTS:
            new_value = _validate_score_string(item_id, field, new_value)
        elif field == "priority_score":
            if new_value is None:
                raise ValueError(f"Field '{field}' cannot be null")
            try:
                new_value = int(new_value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"item {item_id!r}: 'priority_score' must be a number "
                    f"(got {type(new_value).__name__}: {new_value!r})"
                ) from None
        item[field] = new_value
        if field in _SCORE_COMPONENTS:
            _recalc_priority(item)
        _sync_session_status(session)
    return item
