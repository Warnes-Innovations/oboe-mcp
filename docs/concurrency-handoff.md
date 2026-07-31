# Handoff: Add Concurrency Control to oboe-mcp / oboe-cli

## The Problem

Session state is stored as flat JSON files (`session_*.json` + `index.json`) with **zero concurrency protection**. Every mutation follows a naive read-modify-write pattern:

```python
session = load_session(file)   # READ
... modify dict ...            # MODIFY (in memory)
save_session(file, session)    # WRITE (truncates + writes entire file)
_upsert_index(...)             # WRITE (separate file, separate call)
```

This is safe only under single-process access. Concurrent access is not theoretical — it arises from:

- Multiple VS Code windows targeting the same project
- VS Code (via MCP server) + CLI running simultaneously
- Parallel CLI invocations (automation, scripts)
- `mcp.run()` processing sequential requests on a single stdio connection, but **multiple MCP client connections** are possible

## Verified Risks

1. **Lost updates (critical):** Process A loads session, Process B loads session, A writes item 1→completed, B writes item 2→completed. B's write is based on stale data and **reverts item 1 back to pending**.

2. **Truncation race (high):** `save_session()` opens with `"w"` mode which truncates immediately. Concurrent `load_session()` sees an empty file → `JSONDecodeError`.

3. **Session/index inconsistency (high):** No transaction between `save_session()` and `_upsert_index()`. A crash between them leaves the index stale while the session file is updated (or vice versa).

4. **Creation TOCTOU (medium):** `create_session` checks `file.exists()` then writes — two processes can both pass the check.

5. **Index rebuild races (medium):** `list_sessions()` rebuilds `index.json` by scanning all `session_*.json` files. Concurrent writes produce a mixed-time snapshot.

6. **File deletion races (medium):** `trim_sessions()` uses the index to decide what to delete, then deletes files and rebuilds index. Concurrent mutations shift the ground under it.

## All mutation functions are affected

Every function in `src/oboe_mcp/session.py` that calls `save_session()` + `_upsert_index()`:

- `mark_complete`, `mark_skip`, `mark_deferred`, `mark_blocked`, `mark_in_progress`
- `complete_session`, `cancel_session`, `create_child_session`, `complete_child_session`
- `merge_items`, `set_approval`, `update_field`
- `create_session`, `trim_sessions`
- `_upsert_index` itself (read-modify-write on `index.json`)

## Scope of work

Plan an approach that covers:

1. **Atomic writes** — write to temp file, rename into place (prevents truncation races)
2. **File locking** — prevent concurrent read-modify-write by distinct processes on the same file(s)
3. **Transaction-like semantics** — session file + index.json should be consistent
4. **Backward compatibility** — session file format should not change
5. **No new runtime dependencies** — prefer `fcntl.flock` (POSIX) with a fallback or no-op on platforms that don't support it

## Key constraints

- Session files live under `{base_dir}/.github/oboe_sessions/` — a plain directory on shared/local filesystem
- The MCP server uses `mcp.run()` which processes requests sequentially per connection, but multiple connections may exist
- The CLI (`oboe-cli`) is a short-lived process that reads/writes and exits
- Both share the same `session.py` business logic — protection belongs there, not in the transport layer
- `pyproject.toml` dependencies: currently only `mcp>=2.0,<3` — prefer no new library deps

## Design decisions (resolved 2026-07-31 by Dr. Greg)

- **Retry strategy — caller-selectable.** The calling agent chooses between
  **block** (the default) and **fail-fast** when a lock is already held.
  Blocking accepts an **optional timeout**; with no timeout supplied it waits
  indefinitely. Fail-fast raises immediately rather than waiting.
- **Read path — reads take locks.** `load_session`, `list_sessions`, and the
  other read entry points acquire a lock rather than reading unsynchronized.
  A read that feeds a subsequent write holds its lock across the whole
  read-modify-write cycle.

## Design questions still to resolve

These follow from the two decisions above but were not themselves decided:

- **Lock granularity:** per session file, plus a separate lock for `index.json`
  (every mutation touches both). Shared vs. exclusive mode for the read path is
  an open sub-question — `fcntl.flock` offers `LOCK_SH`, which would let
  concurrent readers proceed without blocking each other.
- **Lock ordering / deadlock avoidance:** `create_child_session` locks the
  parent, then creates the child (which locks the child + the index). A single
  documented acquisition order is required. Not yet chosen.
- **Timeout default:** whether "block" with no explicit timeout should wait
  forever or fall back to a generous built-in ceiling.
- **Mechanism and fallback:** `fcntl.flock` on POSIX; behavior on platforms
  without it (fallback vs. documented no-op) is undecided.

## File to modify

Primary: `src/oboe_mcp/session.py`
Possibly: `src/oboe_mcp/server.py` (if transport-layer changes are needed)

## Verification criteria

- Parallel `oboe-cli complete` calls to different items in the same session should not lose updates
- Parallel `oboe-cli` + MCP server operations on the same session should not corrupt data
- `index.json` should remain consistent with session files under concurrent load
- Existing single-process tests should continue to pass
