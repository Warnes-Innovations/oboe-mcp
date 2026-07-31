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

## Remaining questions, as resolved during implementation

- **Lock granularity — one lock per sessions directory.** This *changed* from
  the per-session-file + separate-index-lock plan. Reading the code showed the
  per-file split buys nothing: every mutation writes both a session file and
  the shared `index.json`, so the index lock alone already serializes every
  writer. Per-file locks would have added a real deadlock hazard (see ordering
  below) in exchange for concurrency the index lock forecloses anyway. Readers
  still run in parallel because they take a *shared* lock.
- **Lock ordering — moot under a single lock.** With one lock per directory,
  `create_child_session` and `complete_child_session` cannot deadlock against
  each other; the nested `create_session` / `complete_session` calls re-enter
  the lock the outer operation already holds. Re-entrancy is per-thread and
  depth-counted; escalating a held *shared* lock to exclusive is rejected
  outright, since it would mean releasing mid-operation.
- **Timeout default — 30s, finite.** An unbounded wait on a lock left by a
  wedged process gives the caller no diagnostic and no way out. The error
  names the lock file and the recorded holder. `none` still selects an
  indefinite wait for callers who want it.
- **Mechanism and fallback — `fcntl.flock` on POSIX, `O_CREAT | O_EXCL`
  lockfile elsewhere.** The fallback cannot express shared mode, so readers
  are serialized there; `supports_shared_locks()` reports which is in use
  rather than letting callers assume. The fallback reaps a lockfile whose
  owning PID no longer exists, so a crash cannot wedge a directory forever.
  No new runtime dependencies were added.

## Implementation notes

- New module `src/oboe_mcp/locking.py` holds both primitives.
- `session_transaction()` in `session.py` replaces the hand-written
  load → mutate → `save_session` → `_upsert_index` sequence at every call
  site. The session file and index row are now written under one held lock,
  and an exception inside the block aborts the write entirely.
- The lock file is `.oboe.lock` inside the sessions directory, and is
  gitignored — session files themselves are tracked in this repo, so ignoring
  the directory wholesale was not an option.
- Choosing the policy: `oboe_set_lock_policy` / `oboe_get_lock_policy` (MCP),
  `--lock-timeout` / `--lock-fail-fast` (CLI), or `OBOE_LOCK_POLICY` /
  `OBOE_LOCK_TIMEOUT` (environment).

## Verification

`tests/test_concurrency.py` drives real subprocesses, not threads — the
protection is cross-process, and threads would exercise the re-entrancy path
instead of the failure being guarded against.

The tests were validated by negative control: with the lock made a no-op and
the atomic write reverted to a truncating `open(..., "w")`, **10 of the 14
concurrency tests fail**, including the lost-update, index-consistency, TOCTOU
and truncation cases. The 4 that still pass under the control are API-semantics
tests (re-entrancy, escalation, composite operations), which are not intended
to detect the original bugs.

## File to modify

Primary: `src/oboe_mcp/session.py`
Possibly: `src/oboe_mcp/server.py` (if transport-layer changes are needed)

## Verification criteria

- Parallel `oboe-cli complete` calls to different items in the same session should not lose updates
- Parallel `oboe-cli` + MCP server operations on the same session should not corrupt data
- `index.json` should remain consistent with session files under concurrent load
- Existing single-process tests should continue to pass
