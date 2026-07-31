# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
Concurrency regression tests for OBO session storage.

These use real subprocesses rather than threads: the protection being tested
is cross-process (fcntl.flock / lockfile), and threads inside one interpreter
would exercise the re-entrancy path instead of the thing that actually broke.

Verification criteria from docs/concurrency-handoff.md:
  * parallel completes on different items must not lose updates
  * parallel operations must not corrupt data
  * index.json must stay consistent with the session files
  * existing single-process tests must continue to pass
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from oboe_mcp.locking import (
    LockBusy,
    LockTimeout,
    atomic_write_json,
    policy,
    sessions_lock,
)
from oboe_mcp.session import (
    create_session,
    list_sessions,
    load_session,
    mark_complete,
    session_status,
)

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".github" / "oboe_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_session(sessions_dir: Path, n_items: int = 20) -> Path:
    sf = sessions_dir / "session_20260731_120000.json"
    create_session(
        sf,
        [{"title": f"Item {i}"} for i in range(1, n_items + 1)],
        title="Concurrency test session",
    )
    return sf


def _run_workers(script: str, args_per_worker: list[list[str]]) -> list:
    """Launch one subprocess per arg list, all at once, and collect results."""
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_SRC + os.pathsep + env.get("PYTHONPATH", "")

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for args in args_per_worker
    ]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        results.append((proc.returncode, out.strip(), err.strip()))
    return results


# The worker completes one item.  A barrier on wall-clock start maximizes the
# chance of a genuine interleave rather than accidental serialization.
_COMPLETE_WORKER = """
import sys, time
from pathlib import Path
from oboe_mcp.session import mark_complete

session_file, item_id, start_at = sys.argv[1], sys.argv[2], float(sys.argv[3])
while time.time() < start_at:
    time.sleep(0.001)
mark_complete(Path(session_file), item_id, f"done by worker {item_id}")
print("ok")
"""


# ---------------------------------------------------------------------------
# Lost updates — the critical risk
# ---------------------------------------------------------------------------

def test_parallel_completes_do_not_lose_updates(tmp_path):
    """N processes each complete a different item; all N must survive.

    This is the regression test for the lost-update race: without locking,
    each process writes a whole session document built from a stale read, so
    the last writer reverts every other worker's item to pending.
    """
    sessions_dir = _sessions_dir(tmp_path)
    n = 12
    session_file = _make_session(sessions_dir, n_items=n)

    start_at = time.time() + 1.0
    results = _run_workers(
        _COMPLETE_WORKER,
        [[str(session_file), str(i), str(start_at)] for i in range(1, n + 1)],
    )

    failures = [r for r in results if r[0] != 0]
    assert not failures, f"worker(s) failed: {failures}"

    session = load_session(session_file)
    statuses = {str(i["id"]): i["status"] for i in session["items"]}
    not_completed = [k for k, v in statuses.items() if v != "completed"]
    assert not not_completed, (
        f"{len(not_completed)} of {n} updates were lost: {not_completed}"
    )


def test_index_stays_consistent_with_session_under_parallel_writes(tmp_path):
    """index.json must agree with the session file after concurrent writes."""
    sessions_dir = _sessions_dir(tmp_path)
    n = 10
    session_file = _make_session(sessions_dir, n_items=n)

    start_at = time.time() + 1.0
    results = _run_workers(
        _COMPLETE_WORKER,
        [[str(session_file), str(i), str(start_at)] for i in range(1, n + 1)],
    )
    assert all(r[0] == 0 for r in results)

    stats = session_status(session_file)
    rows = [
        r for r in list_sessions(sessions_dir)
        if r["file"] == session_file.name
    ]
    assert len(rows) == 1, "index should hold exactly one row per session"
    row = rows[0]

    assert stats["open"] == 0
    assert row["open"] == 0, "index still shows open items after all completed"
    assert row["pending"] == 0
    assert row["status"] == "completed"
    assert row["status"] == stats["status"]


def test_index_has_no_duplicate_rows_after_parallel_creates(tmp_path):
    """Concurrent session creation must not produce duplicate index rows."""
    sessions_dir = _sessions_dir(tmp_path)
    script = """
import sys, time
from pathlib import Path
from oboe_mcp.session import create_session

sessions_dir, name, start_at = sys.argv[1], sys.argv[2], float(sys.argv[3])
while time.time() < start_at:
    time.sleep(0.001)
create_session(Path(sessions_dir) / name, [{"title": "x"}], title=name)
print("ok")
"""
    names = [f"session_20260731_1200{i:02d}.json" for i in range(10)]
    start_at = time.time() + 1.0
    results = _run_workers(
        script,
        [[str(sessions_dir), name, str(start_at)] for name in names],
    )
    assert all(r[0] == 0 for r in results), results

    rows = list_sessions(sessions_dir)
    files = [r["file"] for r in rows]
    assert len(files) == len(set(files)), f"duplicate index rows: {files}"
    assert set(files) == set(names), (
        f"index lost sessions: missing {set(names) - set(files)}"
    )


def test_create_session_toctou_only_one_winner(tmp_path):
    """Two processes creating the SAME file: exactly one must win."""
    sessions_dir = _sessions_dir(tmp_path)
    script = """
import sys, time
from pathlib import Path
from oboe_mcp.session import create_session

sessions_dir, name, start_at = sys.argv[1], sys.argv[2], float(sys.argv[3])
while time.time() < start_at:
    time.sleep(0.001)
try:
    create_session(Path(sessions_dir) / name, [{"title": "x"}], title=name)
    print("created")
except FileExistsError:
    print("exists")
"""
    name = "session_20260731_130000.json"
    start_at = time.time() + 1.0
    results = _run_workers(
        script,
        [[str(sessions_dir), name, str(start_at)] for _ in range(6)],
    )
    assert all(r[0] == 0 for r in results), results
    outcomes = [r[1] for r in results]
    assert outcomes.count("created") == 1, (
        f"expected exactly one winner, got {outcomes}"
    )


# ---------------------------------------------------------------------------
# Truncation race
# ---------------------------------------------------------------------------

def test_atomic_write_never_exposes_partial_file(tmp_path):
    """A reader must never observe a truncated or partial document.

    Without atomic writes this fails with JSONDecodeError: the old code opened
    with mode "w", truncating the file before writing the new content.
    """
    target = tmp_path / "big.json"
    payload: dict[str, object] = {
        "items": [{"id": i, "text": "x" * 200} for i in range(500)]
    }
    atomic_write_json(target, payload)

    errors: list[Exception] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                with open(target, encoding="utf-8") as handle:
                    json.load(handle)
            except FileNotFoundError:
                pass  # the rename window is legitimate on some platforms
            except Exception as exc:  # noqa: BLE001 - recording for assertion
                errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for i in range(60):
            payload["revision"] = i
            atomic_write_json(target, payload)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=10)

    assert not errors, f"reader saw a partial file: {errors[:3]}"


# ---------------------------------------------------------------------------
# Lock policy: block / timeout / fail-fast
# ---------------------------------------------------------------------------

_HOLD_LOCK_WORKER = """
import sys, time
from pathlib import Path
from oboe_mcp.locking import sessions_lock

sessions_dir, hold_for = sys.argv[1], float(sys.argv[2])
with sessions_lock(Path(sessions_dir), exclusive=True):
    print("held", flush=True)
    time.sleep(hold_for)
"""


@pytest.fixture
def held_lock(tmp_path):
    """Hold the sessions lock in a separate process for the test's duration."""
    sessions_dir = _sessions_dir(tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_SRC + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK_WORKER, str(sessions_dir), "30"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Wait until the child confirms it actually holds the lock.
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    assert line == "held", f"helper failed to take the lock: {line!r}"
    try:
        yield sessions_dir
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_fail_fast_raises_immediately_when_lock_is_held(held_lock):
    started = time.monotonic()
    with pytest.raises(LockBusy), policy(blocking=False):
        with sessions_lock(held_lock, exclusive=True):
            pass
    assert time.monotonic() - started < 5.0, "fail-fast should not wait"


def test_blocking_times_out_when_lock_stays_held(held_lock):
    started = time.monotonic()
    with pytest.raises(LockTimeout), policy(blocking=True, timeout=1.0):
        with sessions_lock(held_lock, exclusive=True):
            pass
    waited = time.monotonic() - started
    assert waited >= 1.0, "should have waited for the timeout"
    assert waited < 15.0, "should not have waited far beyond the timeout"


def test_blocking_acquires_once_the_holder_releases(tmp_path):
    sessions_dir = _sessions_dir(tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_SRC + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK_WORKER, str(sessions_dir), "2"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "held"

    try:
        with policy(blocking=True, timeout=60.0):
            with sessions_lock(sessions_dir, exclusive=True):
                acquired = True
        assert acquired
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_fail_fast_surfaces_through_a_mutation_call(held_lock):
    """The policy must reach real operations, not just the raw primitive."""
    session_file = held_lock / "session_20260731_120000.json"
    # Build the session before the lock is contended is not possible here, so
    # assert on the failure mode of a mutation against the locked directory.
    with pytest.raises(LockBusy), policy(blocking=False):
        mark_complete(session_file, "1", "should not get this far")


# ---------------------------------------------------------------------------
# Re-entrancy and escalation
# ---------------------------------------------------------------------------

def test_lock_is_reentrant_within_a_process(tmp_path):
    sessions_dir = _sessions_dir(tmp_path)
    with sessions_lock(sessions_dir, exclusive=True):
        with sessions_lock(sessions_dir, exclusive=True):
            with sessions_lock(sessions_dir, exclusive=False):
                pass
    # Released cleanly: a fresh exclusive acquire must still succeed.
    with policy(blocking=False), sessions_lock(sessions_dir, exclusive=True):
        pass


def test_shared_to_exclusive_escalation_is_rejected(tmp_path):
    """Escalation would require releasing mid-operation; refuse it loudly."""
    sessions_dir = _sessions_dir(tmp_path)
    with sessions_lock(sessions_dir, exclusive=False):
        with pytest.raises(ValueError, match="escalate"):
            with sessions_lock(sessions_dir, exclusive=True):
                pass


def test_composite_operation_holds_one_lock_throughout(tmp_path):
    """create_child_session nests create_session; it must not self-deadlock."""
    from oboe_mcp.session import complete_child_session, create_child_session

    sessions_dir = _sessions_dir(tmp_path)
    parent = _make_session(sessions_dir, n_items=3)
    child = sessions_dir / "session_20260731_120500.json"

    with policy(blocking=True, timeout=10.0):
        result = create_child_session(
            parent, child, [{"title": "child work"}],
            title="Child", parent_item_id=1,
        )
    assert result["child_session"]["parent_session_file"] == parent.name
    assert load_session(parent)["active_child_session"] == child.name

    from oboe_mcp.session import mark_complete as _mc

    _mc(child, "1", "child done")
    with policy(blocking=True, timeout=10.0):
        complete_child_session(child, resolution="finished")
    assert load_session(parent)["active_child_session"] is None


# ---------------------------------------------------------------------------
# Reads take locks
# ---------------------------------------------------------------------------

def test_readers_do_not_block_each_other(tmp_path):
    """Shared locks must let concurrent readers proceed together.

    Skipped where the lockfile fallback is in use, which cannot express
    shared mode.
    """
    from oboe_mcp.locking import supports_shared_locks

    if not supports_shared_locks():
        pytest.skip("platform lacks shared locks; readers are serialized")

    sessions_dir = _sessions_dir(tmp_path)
    _make_session(sessions_dir, n_items=3)

    with sessions_lock(sessions_dir, exclusive=False):
        # A second shared acquire from another process must not block.
        env = dict(os.environ)
        env["PYTHONPATH"] = REPO_SRC + os.pathsep + env.get("PYTHONPATH", "")
        script = """
import sys
from pathlib import Path
from oboe_mcp.locking import policy, sessions_lock
with policy(blocking=True, timeout=5.0):
    with sessions_lock(Path(sys.argv[1]), exclusive=False):
        print("ok")
"""
        proc = subprocess.run(
            [sys.executable, "-c", script, str(sessions_dir)],
            env=env, capture_output=True, text=True, timeout=60,
            check=False,  # the assertions below inspect returncode themselves
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "ok"


# ---------------------------------------------------------------------------
# Policy reaches the CLI and MCP surfaces
# ---------------------------------------------------------------------------

def test_cli_fail_fast_flag_reports_the_contended_lock(held_lock, capsys):
    """oboe-cli --lock-fail-fast must exit non-zero with a clear message."""
    from oboe_mcp.cli import main

    base_dir = held_lock.parent.parent
    rc = main([
        "--base-dir", str(base_dir),
        "--lock-fail-fast",
        "sessions",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "lock" in err.lower()


def test_cli_rejects_a_nonsense_lock_timeout(tmp_path, capsys):
    from oboe_mcp.cli import main

    rc = main([
        "--base-dir", str(tmp_path),
        "--lock-timeout", "banana",
        "sessions",
    ])
    assert rc == 1
    assert "--lock-timeout" in capsys.readouterr().err


def test_cli_lock_timeout_none_is_accepted(tmp_path):
    from oboe_mcp.cli import main
    from oboe_mcp.locking import get_default_policy, set_default_policy

    saved = get_default_policy()
    try:
        rc = main([
            "--base-dir", str(tmp_path),
            "--lock-timeout", "none",
            "sessions",
        ])
        assert rc == 0
        assert get_default_policy().timeout is None
    finally:
        set_default_policy(
            blocking=saved.blocking, timeout=saved.timeout
        )


def test_mcp_tool_reports_lock_contention_as_an_error(held_lock):
    """A contended lock must reach the agent as a tool error, not a crash."""
    from oboe_mcp.locking import get_default_policy, set_default_policy
    from oboe_mcp.server import oboe_list_items, oboe_set_lock_policy

    saved = get_default_policy()
    try:
        set_default_policy(blocking=False)
        payload = json.loads(
            oboe_set_lock_policy(blocking=False, timeout_seconds=1.0)
        )
        assert payload["blocking"] is False

        result = oboe_list_items(
            session_file="session_20260731_120000.json",
            base_dir=str(held_lock.parent.parent),
        )
        assert result.startswith("ERROR:"), result
        assert "lock" in result.lower()
    finally:
        set_default_policy(blocking=saved.blocking, timeout=saved.timeout)


def test_writer_waits_for_reader(tmp_path):
    """An exclusive acquire must not proceed while a shared lock is held."""
    sessions_dir = _sessions_dir(tmp_path)
    _make_session(sessions_dir, n_items=3)

    with sessions_lock(sessions_dir, exclusive=False):
        env = dict(os.environ)
        env["PYTHONPATH"] = REPO_SRC + os.pathsep + env.get("PYTHONPATH", "")
        script = """
import sys
from pathlib import Path
from oboe_mcp.locking import LockError, policy, sessions_lock
try:
    with policy(blocking=False):
        with sessions_lock(Path(sys.argv[1]), exclusive=True):
            print("acquired")
except LockError:
    print("blocked")
"""
        proc = subprocess.run(
            [sys.executable, "-c", script, str(sessions_dir)],
            env=env, capture_output=True, text=True, timeout=60,
            check=False,  # the assertions below inspect returncode themselves
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "blocked"
