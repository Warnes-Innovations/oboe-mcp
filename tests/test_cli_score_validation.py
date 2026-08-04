# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""CLI coverage for score-component validation (issue #20).

``oboe-cli create``, ``merge``, ``create-child`` and ``update`` all reach the
same score arithmetic as their MCP counterparts. Each must report a rejected
component as a plain ``❌`` line with a non-zero exit status, not as an
unhandled traceback: ``main()`` catches only ``FileNotFoundError`` and
``LockError``, so anything a command does not catch escapes the process.
"""

import json

import pytest

from oboe_mcp.cli import main
from oboe_mcp.session import create_session

SCORE_COMPONENTS = ("urgency", "importance", "effort", "dependencies")

BAD_ITEMS = [{
    "id": "example",
    "title": "Example item",
    "dependencies": "Blocks the downstream cutover step",
}]


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
    create_session(sf, [{"title": "Alpha"}], title="T", description="D")
    return sf


@pytest.fixture(name="bad_items_file")
def fixture_bad_items_file(tmp_path):
    p = tmp_path / "bad_items.json"
    p.write_text(json.dumps(BAD_ITEMS))
    return p


def assert_clean_rejection(err: str, field: str) -> None:
    assert "❌" in err, err
    assert "unsupported operand" not in err, err
    assert "Traceback" not in err, err
    assert "example" in err, err
    assert field in err, err


def test_create_reports_bad_component_without_a_traceback(
    base_dir, sessions_dir, bad_items_file
):
    """`create` caught only FileExistsError; a ValueError escaped main()."""
    _, err = _run(
        "--base-dir", str(base_dir), "create",
        "--title", "Bad", "--input-file", str(bad_items_file),
        expect_rc=1,
    )
    assert_clean_rejection(err, "dependencies")
    assert list(sessions_dir.glob("session_*.json")) == []


def test_merge_reports_bad_component(base_dir, session_file, bad_items_file):
    _, err = _run(
        "--base-dir", str(base_dir), "--session", session_file.name,
        "merge", "--input-file", str(bad_items_file),
        expect_rc=1,
    )
    assert_clean_rejection(err, "dependencies")


def test_create_child_reports_bad_component(
    base_dir, session_file, bad_items_file
):
    _, err = _run(
        "--base-dir", str(base_dir), "--session", session_file.name,
        "create-child", "--title", "Child",
        "--input-file", str(bad_items_file),
        expect_rc=1,
    )
    assert_clean_rejection(err, "dependencies")


@pytest.mark.parametrize("field", SCORE_COMPONENTS)
def test_update_reports_bad_component(base_dir, session_file, field):
    _, err = _run(
        "--base-dir", str(base_dir), "--session", session_file.name,
        "update", "1", field, "Blocks the cutover",
        expect_rc=1,
    )
    assert "❌" in err, err
    assert "unsupported operand" not in err, err
    assert field in err, err


def test_update_still_accepts_a_numeric_string(base_dir, session_file):
    out, _ = _run(
        "--base-dir", str(base_dir), "--session", session_file.name,
        "update", "1", "urgency", "1",
    )
    assert "priority_score recalculated" in out
