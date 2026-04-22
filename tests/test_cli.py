# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Unit tests for cli.py (the `oboe-cli` command)."""

import json

import pytest

from oboe_mcp.session import create_session, mark_complete, mark_in_progress
from oboe_mcp.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(suffix: str = "120000") -> str:
    return f"session_20260411_{suffix}.json"


def _run(*args: str, expect_rc: int = 0) -> tuple[str, str]:
    """Run oboe-cli main() and return (stdout, stderr).

    Handles both normal return values and sys.exit() calls.
    """
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
        f"Expected rc={expect_rc}, got rc={rc}\n"
        f"stdout: {out}\nstderr: {err}"
    )
    return out, err


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(name="base_dir")
def fixture_base_dir(tmp_path):
    (tmp_path / ".github" / "obo_sessions").mkdir(parents=True)
    return tmp_path


@pytest.fixture(name="sessions_dir")
def fixture_sessions_dir(base_dir):
    return base_dir / ".github" / "obo_sessions"


@pytest.fixture(name="sample_items")
def fixture_sample_items():
    return [
        {"title": "Alpha", "urgency": 5, "importance": 4, "effort": 2, "dependencies": 3},
        {"title": "Beta",  "urgency": 2, "importance": 3, "effort": 4, "dependencies": 1},
        {"title": "Gamma", "urgency": 3, "importance": 3, "effort": 3, "dependencies": 1},
    ]


@pytest.fixture(name="session_file")
def fixture_session_file(sessions_dir, sample_items):
    sf = sessions_dir / _ts()
    create_session(sf, sample_items, title="Test Session", description="A test")
    return sf


@pytest.fixture(name="items_file")
def fixture_items_file(tmp_path, sample_items):
    p = tmp_path / "items.json"
    p.write_text(json.dumps(sample_items))
    return p


# ---------------------------------------------------------------------------
# --help (should not raise, must mention prog name)
# ---------------------------------------------------------------------------

def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_no_command_returns_1():
    rc = main([])
    assert rc == 1


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

def test_sessions_empty_dir(base_dir):
    out, _ = _run("--base-dir", str(base_dir), "sessions")
    assert "No sessions found" in out


def test_sessions_lists_created_session(base_dir, items_file):
    _run("--base-dir", str(base_dir), "create",
         "--title", "My Session", "--input-file", str(items_file))
    out, _ = _run("--base-dir", str(base_dir), "sessions")
    assert "My Session" in out


def test_sessions_filter_active(base_dir, items_file):
    _run("--base-dir", str(base_dir), "create",
         "--title", "Active One", "--input-file", str(items_file))
    out, _ = _run("--base-dir", str(base_dir), "sessions", "--status", "active")
    assert "Active One" in out


def test_sessions_active_flag_shorthand(base_dir, items_file):
    _run("--base-dir", str(base_dir), "create",
         "--title", "Active Two", "--input-file", str(items_file))
    out, _ = _run("--base-dir", str(base_dir), "sessions", "--active")
    assert "Active Two" in out


def test_sessions_filter_completed_empty(base_dir, items_file):
    _run("--base-dir", str(base_dir), "create",
         "--title", "Still Active", "--input-file", str(items_file))
    out, _ = _run("--base-dir", str(base_dir), "sessions", "--status", "completed")
    assert "Still Active" not in out


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def test_create_auto_generates_filename(base_dir, items_file):
    out, _ = _run("--base-dir", str(base_dir), "create",
                  "--title", "Auto", "--input-file", str(items_file))
    assert "Session created" in out
    sessions_dir = base_dir / ".github" / "obo_sessions"
    sf_files = list(sessions_dir.glob("session_*.json"))
    assert len(sf_files) == 1


def test_create_with_explicit_session(base_dir, items_file):
    sf_name = "session_20260411_130000.json"
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", sf_name,
                  "create", "--title", "Explicit", "--input-file", str(items_file))
    assert "Session created" in out
    assert (base_dir / ".github" / "obo_sessions" / sf_name).exists()


def test_create_reports_item_count(base_dir, items_file):
    out, _ = _run("--base-dir", str(base_dir), "create",
                  "--title", "Count", "--input-file", str(items_file))
    assert "Items: 3" in out


def test_create_duplicate_session_returns_error(base_dir, items_file):
    sf_name = "session_20260411_140000.json"
    _run("--base-dir", str(base_dir), "--session", sf_name,
         "create", "--title", "First", "--input-file", str(items_file))
    _, err = _run("--base-dir", str(base_dir), "--session", sf_name,
                  "create", "--title", "Dup", "--input-file", str(items_file),
                  expect_rc=1)
    assert "already exists" in err.lower() or "error" in err.lower()


def test_create_missing_input_file_returns_error(base_dir):
    _, err = _run("--base-dir", str(base_dir), "create",
                  "--title", "Bad", "--input-file", "/nonexistent/items.json",
                  expect_rc=1)
    assert "not found" in err.lower()


def test_create_invalid_json_returns_error(base_dir, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json}")
    _, err = _run("--base-dir", str(base_dir), "create",
                  "--title", "Bad", "--input-file", str(bad),
                  expect_rc=1)
    assert "invalid json" in err.lower()


def test_create_non_array_json_returns_error(base_dir, tmp_path):
    obj_file = tmp_path / "obj.json"
    obj_file.write_text('{"key":"value"}')
    _, err = _run("--base-dir", str(base_dir), "create",
                  "--title", "Bad", "--input-file", str(obj_file),
                  expect_rc=1)
    assert "array" in err.lower()


def test_create_inline_items(base_dir):
    """--items inline JSON should work the same as --input-file."""
    inline = json.dumps([{"title": "Inline task", "id": "t1"}])
    out, _ = _run("--base-dir", str(base_dir), "create",
                  "--title", "Inline Test",
                  "--items", inline)
    assert "Session created" in out
    assert "Items: 1" in out


def test_merge_inline_items(base_dir, session_file):
    """--items inline JSON should work for merge too."""
    inline = json.dumps([{"title": "Merged via inline"}])
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "merge", "--items", inline)
    assert "1 item(s) merged" in out


def test_create_child_inline_items(base_dir, sessions_dir, session_file):
    """create-child should accept --items inline JSON."""
    inline = json.dumps([{"title": "Child inline task"}])
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "create-child",
                  "--title", "Child Inline",
                  "--items", inline)
    assert "Child session created" in out
    assert "Parent session paused" in out


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

def test_merge_appends_items(base_dir, items_file, session_file):
    new_items = [{"title": "Delta"}]
    new_file = base_dir / "new.json"
    new_file.write_text(json.dumps(new_items))

    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "merge", "--input-file", str(new_file))
    assert "1 item(s) merged" in out
    assert "Total items now: 4" in out


def test_merge_missing_session_returns_error(base_dir, items_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", "session_20260411_999999.json",
                  "merge", "--input-file", str(items_file),
                  expect_rc=1)
    assert len(err) > 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def test_status_shows_counts(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "status")
    assert "Total:" in out
    assert "3" in out  # 3 items


def test_status_shows_session_filename(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "status")
    assert session_file.name in out


def test_status_shows_category_breakdown(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "status")
    assert "By Category" in out


def test_status_missing_session_returns_error(base_dir):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", "session_20260411_999999.json",
                  "status", expect_rc=1)
    # argparse or file-not-found error
    assert len(err.strip()) > 0


def test_status_compact_one_line(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "status", "--compact")
    lines = [l for l in out.strip().splitlines() if l.strip()]
    assert len(lines) == 1
    assert "done" in lines[0]
    assert "pending" in lines[0]
    assert "in-progress" in lines[0]
    assert "blocked" in lines[0]


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def test_list_shows_all_items(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "list")
    assert "Alpha" in out
    assert "Beta" in out
    assert "Gamma" in out


def test_list_sorted_by_priority(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "list")
    alpha_pos = out.index("Alpha")
    gamma_pos = out.index("Gamma")
    beta_pos  = out.index("Beta")
    # Alpha score=16, Gamma=10, Beta=8
    assert alpha_pos < gamma_pos < beta_pos


def test_list_filter_by_status(base_dir, session_file):
    mark_complete(session_file, 1, "Done")
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "list", "--status", "completed")
    assert "Alpha" in out
    assert "Beta" not in out
    assert "Gamma" not in out


# ---------------------------------------------------------------------------
# next
# ---------------------------------------------------------------------------

def test_next_shows_highest_priority_item(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "next")
    assert "Alpha" in out
    assert "NEXT ITEM" in out


def test_next_prefers_in_progress(base_dir, session_file):
    mark_in_progress(session_file, 2)
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "next")
    assert "Beta" in out
    assert "RESUMING IN-PROGRESS" in out


def test_next_shows_no_items_when_all_done(base_dir, sessions_dir):
    sf = sessions_dir / "session_20260411_130000.json"
    create_session(sf, [{"title": "Done", "status": "completed"}])
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", sf.name, "next")
    assert "complete" in out.lower() or "no actionable" in out.lower()


def test_next_shows_progress_line(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "next")
    assert "Progress:" in out


def test_next_mark_in_progress_flag(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "next", "--mark-in-progress")
    assert "Progress:" in out
    # Verify the item is now in-progress
    out2, _ = _run("--base-dir", str(base_dir),
                   "--session", session_file.name, "next")
    assert "in-progress" in out2.lower() or "in_progress" in out2.lower()


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def test_show_displays_item_detail(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "show", "1")
    assert "Alpha" in out
    assert "ITEM 1" in out


def test_show_unknown_id_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "show", "999",
                  expect_rc=1)
    assert "not found" in err.lower()


def test_show_string_id(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name, "show", "2")
    assert "Beta" in out


def test_show_fields_limits_output(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "show", "1", "--fields", "id,title,status")
    assert "title" in out
    assert "status" in out
    # Fields not requested should not appear
    assert "description" not in out
    assert "category" not in out


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------

def test_complete_marks_item_done(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "complete", "1", "--resolution", "Fixed the issue")
    assert "marked completed" in out


def test_complete_shows_progress(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "complete", "1", "--resolution", "Done")
    assert "1/3" in out


def test_complete_unknown_id_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "complete", "999", "--resolution", "Done",
                  expect_rc=1)
    assert len(err) > 0


def test_complete_resolution_flag(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "complete", "1", "--resolution", "Fixed via --resolution flag")
    assert "marked completed" in out


def test_complete_requires_resolution(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "complete", "1",
                  expect_rc=2)
    assert "resolution" in err.lower()


# ---------------------------------------------------------------------------
# skip
# ---------------------------------------------------------------------------

def test_skip_marks_item_skipped(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "skip", "2", "Not relevant")
    assert "marked skipped" in out


def test_skip_shows_reason(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "skip", "2", "Out of scope")
    assert "Out of scope" in out


def test_skip_no_reason_accepted(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "skip", "3")
    assert "marked skipped" in out


def test_skip_unknown_id_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "skip", "999",
                  expect_rc=1)
    assert len(err) > 0


# ---------------------------------------------------------------------------
# in-progress
# ---------------------------------------------------------------------------

def test_in_progress_marks_item(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "in-progress", "1")
    assert "marked in progress" in out


def test_in_progress_shows_count(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "in-progress", "1")
    assert "Total in progress: 1" in out


def test_in_progress_unknown_id_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "in-progress", "999",
                  expect_rc=1)
    assert len(err) > 0


# ---------------------------------------------------------------------------
# block
# ---------------------------------------------------------------------------

def test_block_marks_item_blocked(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "block", "1", "Waiting on API access")
    assert "marked blocked" in out


def test_block_shows_blocker_text(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "block", "1", "Waiting on DB schema change")
    assert "Waiting on DB schema change" in out


def test_block_unknown_id_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "block", "999", "reason",
                  expect_rc=1)
    assert len(err) > 0


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

def test_approve_sets_approved(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "approve", "1", "approved")
    assert "approval_status=approved" in out


def test_approve_denied(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "approve", "1", "denied")
    assert "approval_status=denied" in out


def test_approve_with_mode(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "approve", "1", "approved", "--approval-mode", "delayed")
    assert "delayed" in out


def test_approve_with_note(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "approve", "1", "approved", "--approval-note", "Great work")
    assert "Great work" in out


def test_approve_mode_without_approved_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "approve", "1", "denied", "--approval-mode", "delayed",
                  expect_rc=1)
    assert len(err) > 0


def test_approve_unknown_id_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "approve", "999", "approved",
                  expect_rc=1)
    assert len(err) > 0


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def test_update_title_field(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "update", "1", "title", "New Title")
    assert "title = New Title" in out


def test_update_urgency_recalculates_priority(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "update", "1", "urgency", "1")
    assert "priority_score recalculated" in out


def test_update_importance_recalculates_priority(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "update", "1", "importance", "1")
    assert "priority_score recalculated" in out


def test_update_effort_recalculates_priority(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "update", "1", "effort", "5")
    assert "priority_score recalculated" in out


def test_update_invalid_status_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "update", "1", "status", "stalled",
                  expect_rc=1)
    assert len(err) > 0


def test_update_unknown_id_returns_error(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "update", "999", "title", "Ghost",
                  expect_rc=1)
    assert len(err) > 0


# ---------------------------------------------------------------------------
# complete-session
# ---------------------------------------------------------------------------

def test_complete_session_succeeds_when_all_done(base_dir, sessions_dir):
    sf = sessions_dir / "session_20260411_200000.json"
    create_session(sf, [{"title": "Done", "status": "completed"}])
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", sf.name, "complete-session")
    assert "completed" in out.lower()


def test_complete_session_rejects_pending_items(base_dir, session_file):
    _, err = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "complete-session", expect_rc=1)
    assert len(err) > 0


def test_complete_session_shows_final_counts(base_dir, sessions_dir):
    sf = sessions_dir / "session_20260411_201000.json"
    create_session(sf, [
        {"title": "Done", "status": "completed"},
        {"title": "Skip", "status": "skipped"},
    ])
    out, _ = _run("--base-dir", str(base_dir),
                  "--session", sf.name, "complete-session")
    assert "1 completed" in out
    assert "1 skipped" in out


# ---------------------------------------------------------------------------
# create-child / complete-child
# ---------------------------------------------------------------------------

def test_create_child_pauses_parent(base_dir, sessions_dir, session_file, tmp_path):
    child_name = "session_20260411_210000.json"
    new_items = [{"title": "Sub-task"}]
    items_f = tmp_path / "child_items.json"
    items_f.write_text(json.dumps(new_items))

    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "create-child",
                  "--child-session", child_name,
                  "--title", "Child Session",
                  "--parent-item-id", "1",
                  "--input-file", str(items_f))
    assert "Child session created" in out
    assert "Parent session paused" in out
    assert (sessions_dir / child_name).exists()


def test_create_child_without_parent_item_id(base_dir, sessions_dir, session_file, tmp_path):
    child_name = "session_20260411_211000.json"
    items_f = tmp_path / "ci.json"
    items_f.write_text(json.dumps([{"title": "Sub"}]))

    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "create-child",
                  "--child-session", child_name,
                  "--title", "Child",
                  "--input-file", str(items_f))
    assert "Child session created" in out


def test_create_child_auto_generates_filename(base_dir, sessions_dir, session_file, tmp_path):
    """--child-session may be omitted; CLI should auto-generate a valid filename."""
    items_f = tmp_path / "ci.json"
    items_f.write_text(json.dumps([{"title": "Auto-named sub"}]))

    out, _ = _run("--base-dir", str(base_dir),
                  "--session", session_file.name,
                  "create-child",
                  "--title", "Auto Child",
                  "--input-file", str(items_f))
    assert "Child session created" in out
    assert "Parent session paused" in out
    # A file matching session_YYYYMMDD_HHMMSS.json should now exist
    created = [
        f for f in sessions_dir.iterdir()
        if f.name != session_file.name and f.name != "index.json"
    ]
    assert len(created) == 1
    assert created[0].name.startswith("session_")
    assert created[0].name.endswith(".json")


def test_complete_child_resumes_parent(base_dir, sessions_dir, session_file, tmp_path):
    child_name = "session_20260411_212000.json"
    items_f = tmp_path / "ci.json"
    items_f.write_text(json.dumps([{"title": "Sub"}]))

    _run("--base-dir", str(base_dir),
         "--session", session_file.name,
         "create-child",
         "--child-session", child_name,
         "--parent-item-id", "1",
         "--input-file", str(items_f))

    # complete the child item first
    child_sf = sessions_dir / child_name
    mark_complete(child_sf, 1, "sub done")

    out, _ = _run("--base-dir", str(base_dir),
                  "--session", child_name,
                  "complete-child", "Child work finished")
    assert "Child session completed" in out
    assert "Parent session resumed" in out


# ---------------------------------------------------------------------------
# --session required for session-scoped commands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd_args", [
    ["status"],
    ["list"],
    ["next"],
    ["show", "1"],
    ["complete", "1", "--resolution", "done"],
    ["skip", "1"],
    ["in-progress", "1"],
    ["block", "1", "reason"],
    ["approve", "1", "approved"],
    ["update", "1", "title", "X"],
    ["complete-session"],
    ["merge", "--input-file", "/dev/null"],
])
def test_session_required_commands_fail_without_session(base_dir, cmd_args):
    # argparse.error() calls sys.exit(2) — check it doesn't succeed
    try:
        rc = main(["--base-dir", str(base_dir)] + cmd_args)
        assert rc == 1, (
            f"Expected rc=1 (or SystemExit) for {cmd_args!r}, got rc={rc}"
        )
    except SystemExit as exc:
        assert exc.code != 0


def test_auto_infer_session_when_one_active(base_dir, session_file):
    """When --session is omitted and exactly one active session exists, infer it."""
    out, _ = _run("--base-dir", str(base_dir), "status")
    # Should succeed — status output contains totals
    assert "total" in out.lower() or "pending" in out.lower() or "completed" in out.lower()


def test_auto_infer_session_next_when_one_active(base_dir, session_file):
    """next command should auto-infer the single active session."""
    out, _ = _run("--base-dir", str(base_dir), "next")
    assert "NEXT ITEM" in out or "all items" in out.lower()


def test_auto_infer_session_fails_when_multiple_active(base_dir, sessions_dir, session_file, tmp_path):
    """When multiple active sessions exist, --session is required."""
    # Create a second distinct session
    _run("--base-dir", str(base_dir),
         "--session", "session_20260411_130000.json",
         "create",
         "--title", "Second", "--items", json.dumps([{"title": "Task B"}]))
    try:
        rc = main(["--base-dir", str(base_dir), "status"])
        assert rc == 1
    except SystemExit as exc:
        assert exc.code != 0


# ---------------------------------------------------------------------------
# resolve_base_dir  — CWD auto-detection
# ---------------------------------------------------------------------------

def test_resolve_base_dir_uses_cwd_when_obo_sessions_exists(tmp_path, monkeypatch):
    (tmp_path / ".github" / "obo_sessions").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    from oboe_mcp.session import resolve_base_dir
    result = resolve_base_dir()
    assert result == tmp_path


def test_resolve_base_dir_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from oboe_mcp.session import resolve_base_dir
    result = resolve_base_dir()
    assert result == tmp_path


def test_resolve_base_dir_explicit_overrides_cwd(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(tmp_path)
    from oboe_mcp.session import resolve_base_dir
    result = resolve_base_dir(other)
    assert result == other.resolve()


# ---------------------------------------------------------------------------
# Edge cases: sessions command with missing directory
# ---------------------------------------------------------------------------

def test_sessions_with_missing_obo_sessions_dir(tmp_path):
    out, _ = _run("--base-dir", str(tmp_path), "sessions")
    assert "no" in out.lower() or "found" in out.lower()


# ---------------------------------------------------------------------------
# cancel-session command
# ---------------------------------------------------------------------------

def test_cancel_session_command(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir), "--session", session_file.name, "cancel-session")
    assert "cancelled" in out.lower()


def test_cancel_session_with_reason(base_dir, session_file):
    out, _ = _run("--base-dir", str(base_dir), "--session", session_file.name,
                  "cancel-session", "superseded", "by", "newer", "session")
    assert "superseded" in out


def test_cancel_session_reports_open_items(base_dir, session_file, sample_items):
    out, _ = _run("--base-dir", str(base_dir), "--session", session_file.name, "cancel-session")
    # Reports leftover open items
    assert str(len(sample_items)) in out


def test_cancel_session_unknown_file_returns_error(base_dir):
    _, err = _run("--base-dir", str(base_dir), "--session", "session_20260101_000000.json",
                  "cancel-session", expect_rc=1)
    assert len(err.strip()) > 0


# ---------------------------------------------------------------------------
# trim-sessions command
# ---------------------------------------------------------------------------

def test_trim_sessions_command_completed(base_dir, sessions_dir, sample_items):
    from oboe_mcp.session import cancel_session as _cancel
    sf = sessions_dir / "session_20260101_120000.json"
    # Use pre-completed item so session appears completed in index
    create_session(sf, [{"title": "A", "status": "completed"}], title="Old done")

    out, _ = _run("--base-dir", str(base_dir), "trim-sessions", "--before", "now")
    assert "Deleted 1" in out or "1 session" in out
    assert not sf.exists()


def test_trim_sessions_dry_run_output(base_dir, sessions_dir, sample_items):
    sf = sessions_dir / "session_20260101_120000.json"
    create_session(sf, [{"title": "A", "status": "completed"}], title="Old done")

    out, _ = _run("--base-dir", str(base_dir), "trim-sessions", "--before", "now", "--dry-run")
    assert "DRY RUN" in out or "dry" in out.lower()
    assert sf.exists()


def test_trim_sessions_status_any(base_dir, sessions_dir, sample_items):
    from oboe_mcp.session import cancel_session as _cancel
    sf_comp = sessions_dir / "session_20260101_120000.json"
    sf_canc = sessions_dir / "session_20260101_130000.json"
    create_session(sf_comp, [{"title": "A", "status": "completed"}], title="Completed")
    create_session(sf_canc, sample_items, title="Cancelled")
    _cancel(sf_canc)

    out, _ = _run("--base-dir", str(base_dir), "trim-sessions", "--before", "now", "--status", "any")
    assert "Deleted 2" in out or "2 session" in out


def test_trim_sessions_cancelled_status(base_dir, sessions_dir, sample_items):
    from oboe_mcp.session import cancel_session as _cancel
    sf = sessions_dir / "session_20260101_120000.json"
    create_session(sf, sample_items, title="Cancelled")
    _cancel(sf)

    out, _ = _run("--base-dir", str(base_dir), "trim-sessions", "--before", "now", "--status", "cancelled")
    assert "Deleted 1" in out or "1 session" in out
    assert not sf.exists()
