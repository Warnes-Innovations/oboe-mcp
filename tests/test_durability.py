# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Writes must be atomic *and* durable, and a timeout must be a number.

Three defects that were reachable only in the abstract, fixed anyway. A guard
that today's caller cannot trip is still wrong code: the next caller — a test,
another module, a future transport — is not bound by today's schema, and a
crash is not bound by anything.
"""

import json
import os

import pytest

from oboe_mcp.locking import (
    DEFAULT_TIMEOUT,
    LockPolicy,
    _coerce_timeout,
    atomic_write_json,
    atomic_write_text,
    get_default_policy,
    set_default_policy,
)
from oboe_mcp.migrate import migrate_project
from oboe_mcp.server import oboe_set_lock_policy


@pytest.fixture(autouse=True)
def _restore_lock_policy():
    """set_default_policy mutates process state; put it back."""
    before = get_default_policy()
    yield
    set_default_policy(blocking=before.blocking, timeout=before.timeout)


# ---------------------------------------------------------------------------
# Durability: the rename must be fsynced, not just performed
# ---------------------------------------------------------------------------

def _record_fsyncs(monkeypatch) -> list[int]:
    """Capture every fd handed to os.fsync during a write."""
    seen: list[int] = []
    real = os.fsync

    def spy(fd):
        seen.append(fd)
        return real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    return seen


def test_atomic_write_json_fsyncs_file_and_directory(tmp_path, monkeypatch):
    """os.replace is atomic for readers; only fsyncing the dir is durable."""
    seen = _record_fsyncs(monkeypatch)

    atomic_write_json(tmp_path / "out.json", {"a": 1})

    assert len(seen) == 2, (
        f"expected an fsync of the file and of its directory, got {len(seen)}"
    )
    assert json.loads((tmp_path / "out.json").read_text()) == {"a": 1}


def test_atomic_write_text_fsyncs_file_and_directory(tmp_path, monkeypatch):
    seen = _record_fsyncs(monkeypatch)

    atomic_write_text(tmp_path / "out.txt", "hello")

    assert len(seen) == 2
    assert (tmp_path / "out.txt").read_text() == "hello"


def test_a_directory_fsync_failure_does_not_lose_the_write(
    tmp_path, monkeypatch
):
    """Windows and some filesystems refuse it; the write already succeeded."""
    real = os.fsync

    def only_files(fd):
        if os.fstat(fd).st_mode & 0o040000:  # S_IFDIR
            raise OSError("directory fsync unsupported")
        return real(fd)

    monkeypatch.setattr(os, "fsync", only_files)

    atomic_write_json(tmp_path / "out.json", {"a": 1})

    assert json.loads((tmp_path / "out.json").read_text()) == {"a": 1}


def test_atomic_write_leaves_no_temp_file_behind(tmp_path):
    atomic_write_json(tmp_path / "out.json", {"a": 1})
    atomic_write_text(tmp_path / "out.txt", "hi")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.json", "out.txt"]


def test_atomic_write_failure_leaves_the_original_intact(tmp_path):
    """A render that raises must not truncate what is already there."""
    target = tmp_path / "out.json"
    atomic_write_json(target, {"original": True})

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": Unserializable()})

    assert json.loads(target.read_text()) == {"original": True}
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


# ---------------------------------------------------------------------------
# migrate rewrites the user's own files, and must not truncate in place
# ---------------------------------------------------------------------------

def test_migrate_rewrites_atomically(tmp_path, monkeypatch):
    """`Path.write_text` truncates; a crash mid-write loses user content."""
    github = tmp_path / ".github"
    github.mkdir()
    target = github / "copilot-instructions.md"
    target.write_text("Use .github/obo_sessions/ for sessions.\n")

    def no_truncating_writes(*_args, **_kwargs):
        raise AssertionError("migrate must not truncate a file in place")

    monkeypatch.setattr("pathlib.Path.write_text", no_truncating_writes)

    result = migrate_project(tmp_path)

    assert result.changed == [".github/copilot-instructions.md"]
    assert "oboe_sessions" in target.read_text()
    assert "obo_sessions" not in target.read_text()


def test_migrate_preserves_file_mode(tmp_path):
    """A temp file is created 0600; the destination's mode must survive."""
    github = tmp_path / ".github"
    github.mkdir()
    target = github / "copilot-instructions.md"
    target.write_text("Use .github/obo_sessions/ here.\n")
    target.chmod(0o644)

    migrate_project(tmp_path)

    assert target.stat().st_mode & 0o777 == 0o644


def test_migrate_leaves_no_temp_files(tmp_path):
    github = tmp_path / ".github"
    github.mkdir()
    (github / "copilot-instructions.md").write_text(".github/obo_sessions/\n")

    migrate_project(tmp_path)

    assert [p.name for p in github.iterdir()] == ["copilot-instructions.md"]


# ---------------------------------------------------------------------------
# A lock timeout must be a number, whoever is calling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad", ["x", "30", True, False, [], {}, float("nan"), float("inf")]
)
def test_coerce_timeout_rejects_a_non_number(bad):
    with pytest.raises(ValueError, match="[Ll]ock timeout"):
        _coerce_timeout(bad)


@pytest.mark.parametrize("good, expected", [(None, None), (5, 5.0), (2.5, 2.5)])
def test_coerce_timeout_accepts_numbers_and_none(good, expected):
    assert _coerce_timeout(good) == expected


def test_set_default_policy_rejects_a_string_timeout():
    """`timeout <= 0` against a string raised TypeError inside acquisition."""
    with pytest.raises(ValueError, match="[Ll]ock timeout"):
        set_default_policy(blocking=True, timeout="x")  # type: ignore[arg-type]
    assert get_default_policy().timeout == DEFAULT_TIMEOUT


def test_oboe_set_lock_policy_rejects_a_string_timeout():
    result = oboe_set_lock_policy(blocking=True, timeout_seconds="x")  # type: ignore[arg-type]

    assert result.startswith("ERROR: "), result
    assert "internal error" not in result, (
        "a bad argument is input rejection, not an internal defect"
    )
    assert "timeout" in result.lower()


def test_oboe_set_lock_policy_still_accepts_valid_values():
    assert json.loads(
        oboe_set_lock_policy(blocking=True, timeout_seconds=5)
    )["timeout_seconds"] == 5.0
    # Zero or negative means "wait indefinitely".
    assert json.loads(
        oboe_set_lock_policy(blocking=True, timeout_seconds=0)
    )["timeout_seconds"] is None


def test_set_default_policy_normalises_blocking_to_a_bool():
    assert set_default_policy(blocking=1, timeout=5) == LockPolicy(  # type: ignore[arg-type]
        blocking=True, timeout=5.0
    )
