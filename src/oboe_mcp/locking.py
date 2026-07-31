# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
Cross-process locking and atomic writes for OBO session storage.

Session state lives in flat JSON files that are mutated by read-modify-write.
Without protection, two processes (a second VS Code window, the CLI running
alongside the MCP server, a parallel script) can interleave and silently lose
updates or read a half-written file.  This module supplies the two primitives
that prevent that:

* :func:`atomic_write_json` — write to a temp file in the same directory and
  ``os.replace`` it into position, so a reader never observes a truncated or
  partially-written file.
* :func:`sessions_lock` — a cross-process reader/writer lock over a whole
  sessions directory.

Lock scope
----------
The lock covers the **entire sessions directory**, not individual session
files.  Every mutation writes both a ``session_*.json`` file and the shared
``index.json``, so an index lock would serialize all writers regardless; a
per-file lock would add ordering and deadlock hazards while buying no
additional concurrency.  Readers take a shared lock and so still proceed in
parallel with one another.

Lock policy
-----------
The caller chooses what happens when the lock is already held:

* **block** (default) — wait for the lock, up to an optional timeout.
  :data:`DEFAULT_TIMEOUT` applies when no timeout is given; pass ``None`` to
  wait indefinitely.
* **fail-fast** — raise :class:`LockBusy` immediately.

Set the process default with :func:`set_default_policy`, or override for a
region of code with the :func:`policy` context manager.

Platform support
----------------
POSIX uses ``fcntl.flock``, which supports genuine shared and exclusive modes
and is released automatically if the process dies.  Elsewhere a portable
``O_CREAT | O_EXCL`` lockfile fallback is used; it cannot represent shared
mode, so readers are serialized alongside writers.  The fallback reaps a
lockfile whose owning process is gone, so a crash does not wedge the
directory permanently.
"""

import contextlib
import errno
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:  # POSIX
    import fcntl
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - exercised only on non-POSIX
    fcntl = None  # type: ignore[assignment]
    _HAVE_FCNTL = False


__all__ = [
    "DEFAULT_TIMEOUT",
    "LOCK_FILENAME",
    "LockBusy",
    "LockError",
    "LockPolicy",
    "LockTimeout",
    "atomic_write_json",
    "get_default_policy",
    "have_real_locking",
    "policy",
    "sessions_lock",
    "set_default_policy",
    "supports_shared_locks",
]


LOCK_FILENAME = ".oboe.lock"
"""Name of the lock file created inside a sessions directory."""

DEFAULT_TIMEOUT = 30.0
"""Seconds a blocking acquire waits before giving up, when none is given.

Deliberately finite.  An unbounded wait on a lock left behind by a wedged
process gives the caller no diagnostic and no way out; a timeout surfaces the
problem as an error naming the lock file.
"""

_POLL_INITIAL = 0.005
_POLL_MAX = 0.05


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LockError(RuntimeError):
    """Base class for lock acquisition failures."""


class LockBusy(LockError):
    """The lock was held and the caller chose fail-fast."""


class LockTimeout(LockError):
    """The lock was still held when the blocking timeout expired."""


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LockPolicy:
    """How to behave when a lock is already held.

    Attributes:
        blocking: Wait for the lock (True, the default) or raise
            :class:`LockBusy` immediately (False).
        timeout: Seconds to wait when *blocking*.  ``None`` waits forever.
    """

    blocking: bool = True
    timeout: float | None = DEFAULT_TIMEOUT

    def describe(self) -> str:
        if not self.blocking:
            return "fail-fast"
        if self.timeout is None:
            return "block (no timeout)"
        return f"block (timeout {self.timeout:g}s)"


def _policy_from_env() -> LockPolicy:
    """Build the initial default policy from the environment.

    ``OBOE_LOCK_POLICY``  — ``block`` (default) or ``fail-fast``.
    ``OBOE_LOCK_TIMEOUT`` — seconds, or ``none``/empty to wait forever.
    """
    raw_mode = os.environ.get("OBOE_LOCK_POLICY", "").strip().lower()
    blocking = raw_mode not in {"fail-fast", "fail_fast", "failfast", "nowait"}

    timeout: float | None = DEFAULT_TIMEOUT
    raw_timeout = os.environ.get("OBOE_LOCK_TIMEOUT")
    if raw_timeout is not None:
        cleaned = raw_timeout.strip().lower()
        if cleaned in {"", "none", "never", "infinite"}:
            timeout = None
        else:
            try:
                parsed = float(cleaned)
            except ValueError:
                parsed = DEFAULT_TIMEOUT
            timeout = parsed if parsed > 0 else None

    return LockPolicy(blocking=blocking, timeout=timeout)


_state = threading.local()
_default_policy = _policy_from_env()


def get_default_policy() -> LockPolicy:
    """Return the policy used when no scoped override is active."""
    override = getattr(_state, "policy", None)
    return override if override is not None else _default_policy


def set_default_policy(
    blocking: bool = True,
    timeout: float | None = DEFAULT_TIMEOUT,
) -> LockPolicy:
    """Set the process-wide default lock policy and return it."""
    global _default_policy
    _default_policy = LockPolicy(blocking=blocking, timeout=timeout)
    return _default_policy


@contextmanager
def policy(
    blocking: bool = True,
    timeout: float | None = DEFAULT_TIMEOUT,
):
    """Temporarily override the lock policy for the calling thread."""
    previous = getattr(_state, "policy", None)
    _state.policy = LockPolicy(blocking=blocking, timeout=timeout)
    try:
        yield _state.policy
    finally:
        _state.policy = previous


def have_real_locking() -> bool:
    """True when cross-process locking is enforced on this platform."""
    return True  # fcntl on POSIX, O_EXCL lockfile fallback elsewhere


def supports_shared_locks() -> bool:
    """True when readers can hold the lock concurrently.

    False on the lockfile fallback, where a shared request is satisfied by an
    exclusive lock and concurrent readers are therefore serialized.
    """
    return _HAVE_FCNTL


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def atomic_write_json(path: Path, data: object, indent: int = 2) -> None:
    """Serialize *data* to *path* atomically.

    The JSON is written to a temporary file in the same directory, flushed and
    fsynced, then moved into place with :func:`os.replace`.  A concurrent
    reader sees either the previous file or the new one, never a truncated or
    partial one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path: str | None = tmp_name
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=indent)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        tmp_path = None  # ownership transferred to the destination
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Lock acquisition
# ---------------------------------------------------------------------------

def _deadline_for(pol: LockPolicy) -> float | None:
    if not pol.blocking or pol.timeout is None:
        return None
    return time.monotonic() + pol.timeout


def _busy(lock_path: Path, pol: LockPolicy, waited: float) -> LockError:
    holder = _describe_holder(lock_path)
    if pol.blocking:
        return LockTimeout(
            f"Timed out after {waited:.1f}s waiting for the OBO session lock "
            f"at {lock_path}. {holder} If this lock is stale, remove the file. "
            "Raise the wait with OBOE_LOCK_TIMEOUT."
        )
    return LockBusy(
        f"The OBO session lock at {lock_path} is held by another process and "
        f"fail-fast was requested. {holder} "
        "Retry, or use the blocking policy to wait."
    )


def _describe_holder(lock_path: Path) -> str:
    """Best-effort description of who holds the lock, for error messages."""
    try:
        content = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not content:
        return ""
    return f"Lock file records holder: {content}."


def _stamp(lock_path: Path) -> None:
    """Record the current holder in the lock file, best effort."""
    with contextlib.suppress(OSError):
        lock_path.write_text(
            f"pid={os.getpid()} host={_hostname()} at={time.time():.0f}",
            encoding="utf-8",
        )


def _hostname() -> str:
    try:
        import socket

        return socket.gethostname()
    except OSError:  # pragma: no cover - hostname is decorative
        return "unknown"


# --- fcntl (POSIX) ---------------------------------------------------------

@contextmanager
def _flock(lock_path: Path, exclusive: bool, pol: LockPolicy):
    assert fcntl is not None, "_flock requires POSIX fcntl"
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    deadline = _deadline_for(pol)
    started = time.monotonic()

    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        delay = _POLL_INITIAL
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if not pol.blocking:
                    raise _busy(lock_path, pol, 0.0) from None
                if deadline is not None and time.monotonic() >= deadline:
                    raise _busy(
                        lock_path, pol, time.monotonic() - started
                    ) from None
                time.sleep(delay)
                delay = min(delay * 2, _POLL_MAX)

        if exclusive:
            _stamp(lock_path)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


# --- O_EXCL lockfile fallback (non-POSIX) ----------------------------------

def _holder_pid(lock_path: Path) -> int | None:
    try:
        content = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for field in content.split():
        if field.startswith("pid="):
            try:
                return int(field[4:])
            except ValueError:
                return None
    return None


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return True  # cannot tell; assume alive and let the timeout handle it
    return True


def _reap_if_dead(lock_path: Path) -> bool:
    """Remove a lockfile whose owning process no longer exists."""
    pid = _holder_pid(lock_path)
    if pid is None or _process_alive(pid):
        return False
    with contextlib.suppress(OSError):
        os.unlink(lock_path)
        return True
    return False


@contextmanager
def _lockfile(lock_path: Path, exclusive: bool, pol: LockPolicy):
    # The fallback cannot express shared mode; readers take it exclusively.
    del exclusive
    deadline = _deadline_for(pol)
    started = time.monotonic()

    delay = _POLL_INITIAL
    fd = None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
            break
        except FileExistsError:
            if _reap_if_dead(lock_path):
                continue
            if not pol.blocking:
                raise _busy(lock_path, pol, 0.0) from None
            if deadline is not None and time.monotonic() >= deadline:
                raise _busy(lock_path, pol, time.monotonic() - started) from None
            time.sleep(delay)
            delay = min(delay * 2, _POLL_MAX)

    try:
        with contextlib.suppress(OSError):
            os.write(
                fd,
                f"pid={os.getpid()} host={_hostname()} "
                f"at={time.time():.0f}".encode(),
            )
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(lock_path)


# --- public entry point ----------------------------------------------------

def _held() -> dict:
    """Return this thread's map of currently-held locks, keyed by lock path."""
    held = getattr(_state, "held", None)
    if held is None:
        held = {}
        _state.held = held
    return held


@contextmanager
def sessions_lock(
    sessions_dir: Path,
    exclusive: bool = True,
    pol: LockPolicy | None = None,
):
    """Hold a cross-process lock over *sessions_dir*.

    Args:
        sessions_dir: The ``.github/oboe_sessions`` directory to lock.
        exclusive: True for a writer lock, False for a shared reader lock.
        pol: Policy override; defaults to :func:`get_default_policy`.

    Re-entrant within a thread: a nested acquire of a lock already held is a
    no-op, so a composite operation can call into a simpler one without
    self-deadlocking.  Escalating a held shared lock to exclusive is rejected,
    because releasing and re-acquiring mid-operation would break the atomicity
    the caller is relying on.

    Raises:
        LockBusy: fail-fast policy and the lock is held elsewhere.
        LockTimeout: blocking policy and the timeout expired.
        ValueError: a nested acquire tried to escalate shared to exclusive.
    """
    sessions_dir = Path(sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    # Resolve the directory (which now exists) rather than the lock file, so
    # the re-entrancy key is stable whether or not the lock file is present.
    lock_path = sessions_dir.resolve() / LOCK_FILENAME
    key = str(lock_path)

    held = _held()
    existing = held.get(key)
    if existing is not None:
        if exclusive and not existing["exclusive"]:
            raise ValueError(
                "Cannot escalate a shared OBO session lock to exclusive while "
                f"it is held ({lock_path}). Acquire the exclusive lock first."
            )
        existing["depth"] += 1
        try:
            yield
        finally:
            existing["depth"] -= 1
            if existing["depth"] == 0:
                held.pop(key, None)
        return

    effective = pol if pol is not None else get_default_policy()
    acquire = _flock if _HAVE_FCNTL else _lockfile

    with acquire(lock_path, exclusive, effective):
        held[key] = {"exclusive": exclusive, "depth": 1}
        try:
            yield
        finally:
            held.pop(key, None)
