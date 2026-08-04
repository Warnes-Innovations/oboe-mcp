# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""`trim_sessions` deletes files, and decides what to delete from
`index.json` — a file this code did not write, that is routinely
committed and synced between machines. A planted row of
`../../IMPORTANT.txt` was unlinked and still reported as a deleted
session.

Every case here was reproduced against the unfixed code first."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from oboe_mcp.cli import main
from oboe_mcp.server import oboe_trim_sessions
from oboe_mcp.session import (
    _deletable_session,
    create_session,
    mark_complete,
    trim_sessions,
)


def _run(*args: str, expect_rc: int = 0) -> tuple[str, str]:
    """Run oboe-cli main() and return (stdout, stderr)."""
    from io import StringIO
    import sys

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = StringIO()
    sys.stderr = StringIO()
    rc: int = 0
    try:
        rc = main(list(args))
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    finally:
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()
        sys.stdout, sys.stderr = old_out, old_err

    assert rc == expect_rc, (
        f"Expected rc={expect_rc}, got rc={rc}\nstdout: {out}\nstderr: {err}"
    )
    return out, err


@pytest.fixture(name="base_dir")
def fixture_base_dir(tmp_path):
    (tmp_path / ".github" / "oboe_sessions").mkdir(parents=True)
    return tmp_path


@pytest.fixture(name="sessions_dir")
def fixture_sessions_dir(base_dir):
    return base_dir / ".github" / "oboe_sessions"


@pytest.fixture(name="session_file")
def fixture_session_file(sessions_dir):
    sf = sessions_dir / "session_20260411_120000.json"
    create_session(
        sf, [{"id": 1, "title": "Alpha"}], title="T", description="D"
    )
    return sf


# ---------------------------------------------------------------------------
# 1. trim_sessions must not delete outside the sessions directory
# ---------------------------------------------------------------------------

def _plant_row(sessions_dir, **row) -> None:
    """Append a row to index.json, as a hand-edit or a bad sync would."""
    path = sessions_dir / "index.json"
    idx = (
        json.loads(path.read_text())
        if path.exists()
        else {"format_version": 1, "last_updated": "", "sessions": []}
    )
    idx["sessions"].append(
        {"status": "completed", "created": "2026-01-01", **row}
    )
    path.write_text(json.dumps(idx))


def test_trim_refuses_a_traversing_index_row(base_dir, sessions_dir):
    """A row of '../../X' unlinked a real file outside the tree."""
    victim = base_dir / "IMPORTANT.txt"
    victim.write_text("user data")
    sf = sessions_dir / "session_20260411_120000.json"
    create_session(sf, [{"id": 1, "title": "A"}], title="T", description="D")
    mark_complete(sf, 1, "done")
    _plant_row(sessions_dir, file="../../IMPORTANT.txt")

    result = trim_sessions(
        sessions_dir, before="now", status_filter="completed"
    )

    assert victim.exists(), "deleted a file outside the sessions directory"
    assert victim.read_text() == "user data"
    assert "../../IMPORTANT.txt" not in result["deleted"]
    assert any("IMPORTANT" in note for note in result["rejected"])


def test_trim_refuses_an_absolute_index_row(base_dir, sessions_dir):
    victim = base_dir / "ABSOLUTE.txt"
    victim.write_text("user data")
    _plant_row(sessions_dir, file=str(victim))

    result = trim_sessions(
        sessions_dir, before="now", status_filter="completed"
    )

    assert victim.exists()
    assert result["rejected"]


def test_trim_refuses_a_symlink_out_of_the_tree(base_dir, sessions_dir):
    """Name checks cannot see a symlink; the containment check can."""
    victim = base_dir / "LINKED.txt"
    victim.write_text("user data")
    link = sessions_dir / "session_20260101_000000.json"
    link.symlink_to(victim)
    _plant_row(sessions_dir, file=link.name)

    result = trim_sessions(
        sessions_dir, before="now", status_filter="completed"
    )

    assert victim.exists(), "followed a symlink out of the sessions directory"
    assert result["rejected"]


def test_trim_does_not_report_a_row_with_no_file_as_deleted(sessions_dir):
    """'' joined to the directory itself, and was still counted as deleted."""
    _plant_row(sessions_dir, title="no file key")

    result = trim_sessions(
        sessions_dir, before="now", status_filter="completed"
    )

    assert "" not in result["deleted"]
    assert sessions_dir.is_dir()


def test_trim_deleted_list_reflects_what_was_actually_removed(sessions_dir):
    sf = sessions_dir / "session_20260411_120000.json"
    create_session(sf, [{"id": 1, "title": "A"}], title="T", description="D")
    mark_complete(sf, 1, "done")

    result = trim_sessions(
        sessions_dir, before="now", status_filter="completed"
    )

    assert result["deleted"] == [sf.name]
    assert not sf.exists()


def test_trim_dry_run_touches_nothing(sessions_dir):
    sf = sessions_dir / "session_20260411_120000.json"
    create_session(sf, [{"id": 1, "title": "A"}], title="T", description="D")
    mark_complete(sf, 1, "done")

    result = trim_sessions(
        sessions_dir, before="now", status_filter="completed", dry_run=True
    )

    assert result["deleted"] == [sf.name]
    assert sf.exists()


def test_cli_trim_reports_refused_rows(base_dir, sessions_dir):
    victim = base_dir / "IMPORTANT.txt"
    victim.write_text("user data")
    _plant_row(sessions_dir, file="../../IMPORTANT.txt")

    _, err = _run(
        "--base-dir", str(base_dir), "trim-sessions", "--before", "now",
    )
    assert "Refused" in err
    assert "IMPORTANT" in err
    assert victim.exists()


@pytest.mark.parametrize(
    "name",
    ["", "../evil.json", "sub/session_20260411_120000.json",
     "/etc/passwd", "notes.txt", "session_bad.json"],
)
def test_deletable_session_rejects(sessions_dir, name):
    with pytest.raises(ValueError):
        _deletable_session(sessions_dir, name)


def test_deletable_session_accepts_a_real_session_name(sessions_dir):
    target = _deletable_session(sessions_dir, "session_20260411_120000.json")
    assert target.parent == sessions_dir


# ---------------------------------------------------------------------------
# 7. trim_sessions and an offset-aware `before`
# ---------------------------------------------------------------------------

def test_trim_accepts_a_timezone_aware_before(base_dir, sessions_dir):
    """An ISO-8601 string with an offset raised TypeError mid-delete."""
    sf = sessions_dir / "session_20260411_120000.json"
    create_session(sf, [{"id": 1, "title": "A"}], title="T", description="D")
    mark_complete(sf, 1, "done")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    result = trim_sessions(
        sessions_dir, before=future, status_filter="completed", dry_run=True
    )
    assert result["deleted"] == [sf.name]


def test_oboe_trim_accepts_a_timezone_aware_before(base_dir, sessions_dir):
    # A completed session must exist, or the age comparison never runs and
    # the test cannot see the failure it exists to catch.
    sf = sessions_dir / "session_20260411_120000.json"
    create_session(sf, [{"id": 1, "title": "A"}], title="T", description="D")
    mark_complete(sf, 1, "done")

    result = oboe_trim_sessions(
        base_dir=str(base_dir), before="2126-04-01T00:00:00+00:00",
        dry_run=True,
    )
    assert not result.startswith("ERROR: "), result
    assert json.loads(result)["deleted"] == [sf.name]


