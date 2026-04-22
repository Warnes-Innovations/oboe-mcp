# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Unit tests for session.py."""

import json
import pytest

from oboe_mcp.session import (
    complete_child_session,
    complete_session,
    create_child_session,
    create_session,
    cancel_session,
    trim_sessions,
    get_item,
    get_next,
    list_items,
    list_sessions,
    mark_blocked,
    mark_complete,
    mark_in_progress,
    mark_skip,
    merge_items,
    obo_sessions_dir,
    resolve_session_file,
    set_approval,
    session_status,
    update_field,
    validate_session_filename,
    _is_valid_index,
    _rebuild_index_from_files,
    _recalc_priority,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(name="sessions_dir")
def fixture_sessions_dir(tmp_path):
    d = tmp_path / ".github" / "obo_sessions"
    d.mkdir(parents=True)
    return d


@pytest.fixture(name="sample_items")
def fixture_sample_items():
    return [
        {
            "title": "Alpha",
            "urgency": 5,
            "importance": 4,
            "effort": 2,
            "dependencies": 3,
        },
        {
            "title": "Beta",
            "urgency": 2,
            "importance": 3,
            "effort": 4,
            "dependencies": 1,
        },
        {
            "title": "Gamma",
            "urgency": 3,
            "importance": 3,
            "effort": 3,
            "dependencies": 1,
        },
    ]


@pytest.fixture(name="session_file")
def fixture_session_file(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_120000.json"
    create_session(
        sf,
        sample_items,
        title="Test Session",
        description="A test",
    )
    return sf


# ---------------------------------------------------------------------------
# Priority score
# ---------------------------------------------------------------------------

def test_recalc_priority_formula():
    item = {"urgency": 4, "importance": 5, "effort": 2, "dependencies": 3}
    score = _recalc_priority(item)
    assert score == 4 + 5 + (6 - 2) + 3  # == 16
    assert item["priority_score"] == 16


def test_default_priority_score():
    item = {}
    _recalc_priority(item)
    # defaults: urgency=3, importance=3, effort=3, dependencies=1
    assert item["priority_score"] == 3 + 3 + (6 - 3) + 1  # == 10


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------

def test_create_session_creates_file(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_130000.json"
    session = create_session(sf, sample_items, title="My Session")
    assert sf.exists()
    assert session["title"] == "My Session"
    assert len(session["items"]) == 3


def test_create_session_updates_index(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_140000.json"
    create_session(sf, sample_items, title="Indexed Session")
    idx_path = sessions_dir / "index.json"
    assert idx_path.exists()
    index = json.loads(idx_path.read_text())
    files = [s["file"] for s in index["sessions"]]
    assert sf.name in files


def test_create_session_assigns_ids(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_150000.json"
    session = create_session(sf, sample_items)
    ids = [i["id"] for i in session["items"]]
    assert ids == [1, 2, 3]


def test_create_session_raises_if_exists(session_file, sample_items):
    with pytest.raises(FileExistsError):
        create_session(session_file, sample_items)


def test_create_session_calculates_priority(sessions_dir):
    items = [
        {
            "title": "X",
            "urgency": 5,
            "importance": 5,
            "effort": 1,
            "dependencies": 5,
        }
    ]
    sf = sessions_dir / "session_20260314_160000.json"
    session = create_session(sf, items)
    assert (
        session["items"][0]["priority_score"] == 5 + 5 + (6 - 1) + 5
    )


def test_create_session_accepts_blocked_item_status(sessions_dir):
    sf = sessions_dir / "session_20260314_160500.json"
    session = create_session(
        sf,
        [{
            "title": "Waiting",
            "status": "blocked",
            "blocker": {"summary": "Awaiting dependency"},
        }],
    )
    assert session["items"][0]["status"] == "blocked"
    assert session["items"][0]["blocker"] == {"summary": "Awaiting dependency"}


def test_create_session_accepts_deferred_item_status(sessions_dir):
    sf = sessions_dir / "session_20260314_160600.json"
    session = create_session(
        sf,
        [{
            "title": "Later",
            "status": "deferred",
            "approval_status": "approved",
            "approval_mode": "delayed",
        }],
    )
    item = session["items"][0]
    assert item["status"] == "deferred"
    assert item["approval_status"] == "approved"
    assert item["approval_mode"] == "delayed"


def test_create_session_rejects_invalid_filename(sessions_dir, sample_items):
    sf = sessions_dir / "bad_session_name.json"
    with pytest.raises(ValueError, match="Invalid session filename"):
        create_session(sf, sample_items)


# ---------------------------------------------------------------------------
# get_next
# ---------------------------------------------------------------------------

def test_get_next_returns_highest_priority_pending(session_file):
    # Alpha: 5+4+(6-2)+3 = 16, Beta: 2+3+(6-4)+1 = 8,
    # Gamma: 3+3+(6-3)+1 = 10
    item = get_next(session_file)
    assert item["title"] == "Alpha"
    assert item["priority_score"] == 16


def test_get_next_prefers_in_progress(session_file):
    # Mark Beta as in_progress; Alpha has higher score,
    # but in_progress takes precedence.
    update_field(session_file, 2, "status", "in_progress")
    item = get_next(session_file)
    assert item["title"] == "Beta"


def test_get_next_returns_none_when_all_done(sessions_dir):
    items = [
        {"title": "Done", "status": "completed"},
        {"title": "Skip", "status": "skipped"},
    ]
    sf = sessions_dir / "session_20260314_170000.json"
    create_session(sf, items)
    assert get_next(sf) is None


def test_get_next_all_pending(sessions_dir):
    items = [
        {
            "title": "Low",
            "urgency": 1,
            "importance": 1,
            "effort": 5,
            "dependencies": 1,
        },
        {
            "title": "High",
            "urgency": 5,
            "importance": 5,
            "effort": 1,
            "dependencies": 5,
        },
    ]
    sf = sessions_dir / "session_20260314_180000.json"
    create_session(sf, items)
    item = get_next(sf)
    assert item["title"] == "High"


def test_get_next_skips_blocked_items(sessions_dir):
    items = [
        {
            "title": "Blocked High",
            "status": "blocked",
            "blocker": {"summary": "Waiting on API access"},
            "urgency": 5,
            "importance": 5,
            "effort": 1,
            "dependencies": 5,
        },
        {
            "title": "Ready",
            "urgency": 3,
            "importance": 3,
            "effort": 3,
            "dependencies": 1,
        },
    ]
    sf = sessions_dir / "session_20260314_181000.json"
    create_session(sf, items)
    item = get_next(sf)
    assert item["title"] == "Ready"


def test_get_next_returns_deferred_when_no_pending_items(sessions_dir):
    items = [
        {
            "title": "Later",
            "status": "deferred",
            "approval_status": "approved",
            "approval_mode": "delayed",
            "urgency": 5,
            "importance": 4,
            "effort": 2,
            "dependencies": 3,
        },
        {"title": "Done", "status": "completed"},
    ]
    sf = sessions_dir / "session_20260314_181250.json"
    create_session(sf, items)
    item = get_next(sf)
    assert item["title"] == "Later"
    assert item["status"] == "deferred"


def test_get_next_raises_for_paused_parent(session_file, sessions_dir):
    child_sf = sessions_dir / "session_20260314_181500.json"
    create_child_session(
        session_file,
        child_sf,
        [{"title": "Subtask"}],
        title="Child",
        parent_item_id=1,
    )
    with pytest.raises(ValueError, match="paused by active child session"):
        get_next(session_file)


# ---------------------------------------------------------------------------
# mark_complete
# ---------------------------------------------------------------------------

def test_mark_complete_sets_status(session_file):
    session = mark_complete(session_file, 1, "Fixed it")
    item = next(i for i in session["items"] if i["id"] == 1)
    assert item["status"] == "completed"
    assert item["resolution"] == "Fixed it"


def test_mark_complete_updates_index(session_file):
    mark_complete(session_file, 1, "Done")
    idx = json.loads((session_file.parent / "index.json").read_text())
    entry = next(s for s in idx["sessions"] if s["file"] == session_file.name)
    # 3 items total, 1 completed → 2 pending
    assert entry["pending"] == 2


def test_mark_complete_raises_on_unknown_id(session_file):
    with pytest.raises(KeyError):
        mark_complete(session_file, 999, "N/A")


# ---------------------------------------------------------------------------
# mark_skip
# ---------------------------------------------------------------------------

def test_mark_skip_sets_status(session_file):
    session = mark_skip(session_file, 2, "Not relevant")
    item = next(i for i in session["items"] if i["id"] == 2)
    assert item["status"] == "skipped"
    assert item["skip_reason"] == "Not relevant"


def test_mark_skip_no_reason(session_file):
    session = mark_skip(session_file, 3)
    item = next(i for i in session["items"] if i["id"] == 3)
    assert item["status"] == "skipped"


def test_mark_blocked_sets_status_and_blocker(session_file):
    session = mark_blocked(session_file, 2, "Waiting on schema decision")
    item = next(i for i in session["items"] if i["id"] == 2)
    assert item["status"] == "blocked"
    assert item["blocker"] == {"summary": "Waiting on schema decision"}
    assert item["blocked_at"] is not None


def test_mark_blocked_updates_index(session_file):
    mark_blocked(session_file, 2, "Waiting on schema decision")
    idx = json.loads((session_file.parent / "index.json").read_text())
    entry = next(s for s in idx["sessions"] if s["file"] == session_file.name)
    assert entry["blocked"] == 1
    assert entry["actionable"] == 2
    assert entry["open"] == 3


def test_mark_in_progress_sets_status(session_file):
    session = mark_in_progress(session_file, 2)
    item = next(i for i in session["items"] if i["id"] == 2)
    assert item["status"] == "in_progress"


def test_mark_in_progress_updates_index(session_file):
    mark_in_progress(session_file, 2)
    idx = json.loads((session_file.parent / "index.json").read_text())
    entry = next(s for s in idx["sessions"] if s["file"] == session_file.name)
    assert entry["pending"] == 2
    assert entry["in_progress"] == 1
    assert entry["actionable"] == 3


# ---------------------------------------------------------------------------
# update_field
# ---------------------------------------------------------------------------

def test_update_field_recalculates_priority_on_score_change(session_file):
    item = update_field(session_file, 1, "urgency", "1")
    # new: 1+4+(6-2)+3 = 12
    assert item["priority_score"] == 1 + 4 + (6 - 2) + 3


def test_update_field_importance_recalculates(session_file):
    item = update_field(session_file, 1, "importance", "2")
    # original urgency=5: 5+2+(6-2)+3 = 14
    assert item["priority_score"] == 5 + 2 + (6 - 2) + 3


def test_update_field_effort_recalculates(session_file):
    item = update_field(session_file, 1, "effort", "5")
    # 5+4+(6-5)+3 = 13
    assert item["priority_score"] == 5 + 4 + (6 - 5) + 3


def test_update_field_non_score_no_recalc(session_file):
    original_score = get_item(session_file, 1)["priority_score"]
    item = update_field(session_file, 1, "title", "New Title")
    assert item["title"] == "New Title"
    assert item["priority_score"] == original_score


def test_update_field_status_updates_index(session_file):
    update_field(session_file, 1, "status", "in_progress")
    idx = json.loads((session_file.parent / "index.json").read_text())
    entry = next(s for s in idx["sessions"] if s["file"] == session_file.name)
    assert entry["pending"] == 2
    assert entry["in_progress"] == 1
    assert entry["actionable"] == 3


def test_update_field_accepts_blocked_status(session_file):
    item = update_field(session_file, 1, "status", "blocked")
    assert item["status"] == "blocked"


def test_update_field_accepts_deferred_status(session_file):
    item = update_field(session_file, 1, "status", "deferred")
    assert item["status"] == "deferred"


def test_update_field_sets_approval_status(session_file):
    item = update_field(session_file, 1, "approval_status", "approved")
    assert item["approval_status"] == "approved"
    assert item["approved_at"] is not None


def test_update_field_sets_approval_mode_and_backfills_approval_status(
    session_file,
):
    item = update_field(session_file, 1, "approval_mode", "delayed")
    assert item["approval_mode"] == "delayed"
    assert item["approval_status"] == "approved"
    assert item["approved_at"] is not None


def test_update_field_rejects_invalid_approval_status(session_file):
    with pytest.raises(ValueError, match="Invalid approval status"):
        update_field(session_file, 1, "approval_status", "maybe")


def test_update_field_rejects_invalid_approval_mode(session_file):
    with pytest.raises(ValueError, match="Invalid approval mode"):
        update_field(session_file, 1, "approval_mode", "soon")


def test_update_field_rejects_invalid_status(session_file):
    with pytest.raises(ValueError, match="Invalid item status"):
        update_field(session_file, 1, "status", "stalled")


def test_set_approval_defaults_approved_items_to_immediate(session_file):
    item = set_approval(session_file, 1, "approved")
    assert item["approval_status"] == "approved"
    assert item["approval_mode"] == "immediate"
    assert item["approved_at"] is not None


def test_set_approval_delayed_moves_item_to_deferred(session_file):
    item = set_approval(
        session_file,
        1,
        "approved",
        approval_mode="delayed",
        note="Review now, implement later",
    )
    assert item["approval_status"] == "approved"
    assert item["approval_mode"] == "delayed"
    assert item["status"] == "deferred"
    assert item["approval_note"] == "Review now, implement later"


def test_set_approval_can_pair_denial_with_skipped_lifecycle(session_file):
    item = set_approval(
        session_file,
        1,
        "denied",
        lifecycle_status="skipped",
        note="Rejected during review",
    )
    assert item["approval_status"] == "denied"
    assert item["approval_mode"] is None
    assert item["approved_at"] is None
    assert item["status"] == "skipped"
    assert item["approval_note"] == "Rejected during review"


def test_set_approval_rejects_mode_without_approved_status(session_file):
    with pytest.raises(ValueError, match="approval_mode"):
        set_approval(session_file, 1, "denied", approval_mode="delayed")


def test_update_field_raises_on_unknown_id(session_file):
    with pytest.raises(KeyError):
        update_field(session_file, 999, "title", "Ghost")


# ---------------------------------------------------------------------------
# list_items
# ---------------------------------------------------------------------------

def test_list_items_sorted_by_priority(session_file):
    items = list_items(session_file)
    scores = [i["priority_score"] for i in items]
    assert scores == sorted(scores, reverse=True)


def test_list_items_status_filter(session_file):
    mark_complete(session_file, 1, "Done")
    completed = list_items(session_file, status_filter="completed")
    assert len(completed) == 1
    assert completed[0]["id"] == 1


# ---------------------------------------------------------------------------
# session_status
# ---------------------------------------------------------------------------

def test_session_status_counts(session_file):
    mark_complete(session_file, 1, "Done")
    mark_skip(session_file, 2, "Skip")
    stats = session_status(session_file)
    assert stats["total"] == 3
    assert stats["completed"] == 1
    assert stats["skipped"] == 1
    assert stats["pending"] == 1
    assert stats["done"] == 2


def test_session_status_counts_blocked(session_file):
    mark_blocked(session_file, 2, "Waiting on dependency")
    stats = session_status(session_file)
    assert stats["blocked"] == 1
    assert stats["open"] == 3


def test_session_status_counts_deferred_and_approval(session_file):
    update_field(session_file, 1, "approval_mode", "delayed")
    update_field(session_file, 1, "status", "deferred")
    stats = session_status(session_file)
    assert stats["deferred"] == 1
    assert stats["approval"]["approved"] == 1
    assert stats["approval"]["unreviewed"] == 2


def test_session_auto_completes_when_no_actionable_items(sessions_dir):
    sf = sessions_dir / "session_20260314_171000.json"
    create_session(sf, [{"title": "Done Me"}])
    session = mark_complete(sf, 1, "done")
    assert session["status"] == "completed"
    assert session["completed_at"]

    idx = json.loads((sessions_dir / "index.json").read_text())
    entry = next(s for s in idx["sessions"] if s["file"] == sf.name)
    assert entry["status"] == "completed"
    assert entry["actionable"] == 0


def test_complete_session_rejects_blocked_items(sessions_dir):
    sf = sessions_dir / "session_20260314_171500.json"
    create_session(
        sf,
        [{
            "title": "Blocked",
            "status": "blocked",
            "blocker": {"summary": "Need DBA input"},
        }],
    )
    with pytest.raises(ValueError, match="blocked"):
        complete_session(sf)


def test_complete_session_rejects_deferred_items(sessions_dir):
    sf = sessions_dir / "session_20260314_171550.json"
    create_session(
        sf,
        [{
            "title": "Deferred",
            "status": "deferred",
            "approval_status": "approved",
            "approval_mode": "delayed",
        }],
    )
    with pytest.raises(ValueError, match="deferred"):
        complete_session(sf)


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

def test_list_sessions_reads_index(sessions_dir, session_file):
    rows = list_sessions(sessions_dir)
    assert any(r["file"] == session_file.name for r in rows)


def test_list_sessions_fallback_no_index(tmp_path):
    d = tmp_path / ".github" / "obo_sessions"
    d.mkdir(parents=True)
    # Write session file directly without creating index
    sf = d / "session_20260314_190000.json"
    items = [
        {
            "title": "X",
            "urgency": 3,
            "importance": 3,
            "effort": 3,
            "dependencies": 1,
        }
    ]
    from datetime import datetime
    session_data = {
        "session_file": sf.name,
        "created": datetime.now().isoformat(),
        "title": "Direct Write",
        "description": "",
        "status": "active",
        "items": [
            dict(
                items[0],
                id=1,
                status="pending",
                category="General",
                description="",
                resolution=None,
                skip_reason=None,
                priority_score=10,
            )
        ],
    }
    sf.write_text(json.dumps(session_data))
    rows = list_sessions(d)
    assert len(rows) == 1
    assert rows[0]["file"] == sf.name
    # Index should now be created
    assert (d / "index.json").exists()


def test_list_sessions_status_filter_incomplete(sessions_dir, session_file):
    rows = list_sessions(sessions_dir, status_filter="incomplete")
    # Session has 3 pending items → should appear
    assert any(r["file"] == session_file.name for r in rows)


def test_list_sessions_status_filter_incomplete_includes_deferred_only(
    sessions_dir,
):
    sf = sessions_dir / "session_20260314_190500.json"
    create_session(
        sf,
        [{
            "title": "Deferred",
            "status": "deferred",
            "approval_status": "approved",
            "approval_mode": "delayed",
        }],
    )
    rows = list_sessions(sessions_dir, status_filter="incomplete")
    entry = next(r for r in rows if r["file"] == sf.name)
    assert entry["deferred"] == 1


def test_list_sessions_status_filter_completed(sessions_dir, session_file):
    rows = list_sessions(sessions_dir, status_filter="completed")
    # Session is active → should NOT appear
    assert not any(r["file"] == session_file.name for r in rows)


def test_list_sessions_status_filter_paused(sessions_dir, session_file):
    child_sf = sessions_dir / "session_20260314_194500.json"
    create_child_session(
        session_file,
        child_sf,
        [{"title": "Nested"}],
        title="Child",
        parent_item_id=1,
    )
    rows = list_sessions(sessions_dir, status_filter="paused")
    assert any(r["file"] == session_file.name for r in rows)


def test_list_sessions_status_filter_incomplete_includes_in_progress_only(
    sessions_dir,
):
    sf = sessions_dir / "session_20260314_195000.json"
    create_session(sf, [{"title": "Only Item"}])
    mark_in_progress(sf, 1)
    rows = list_sessions(sessions_dir, status_filter="incomplete")
    assert any(r["file"] == sf.name for r in rows)


def test_create_child_session_pauses_parent_and_blocks_item(
    session_file,
    sessions_dir,
):
    child_sf = sessions_dir / "session_20260314_200000.json"
    result = create_child_session(
        session_file,
        child_sf,
        [{"title": "Nested Task"}],
        title="Child Session",
        description="child",
        parent_item_id=2,
    )
    parent_session = result["parent_session"]
    child_session = result["child_session"]

    assert parent_session["status"] == "paused"
    assert parent_session["active_child_session"] == child_sf.name
    blocked_item = next(i for i in parent_session["items"] if i["id"] == 2)
    assert blocked_item["status"] == "blocked"
    assert blocked_item["blocker"]["session_file"] == child_sf.name
    assert child_session["parent_session_file"] == session_file.name
    assert child_session["parent_item_id"] == 2


def test_complete_child_session_resumes_parent(session_file, sessions_dir):
    child_sf = sessions_dir / "session_20260314_201000.json"
    create_child_session(
        session_file,
        child_sf,
        [{"title": "Nested Task"}],
        title="Child Session",
        parent_item_id=2,
    )
    mark_complete(child_sf, 1, "Child done")

    result = complete_child_session(
        child_sf,
        resolution="Nested work finished",
    )
    parent_session = result["parent_session"]
    child_session = result["child_session"]

    assert child_session["status"] == "completed"
    assert parent_session["status"] == "active"
    assert parent_session["active_child_session"] is None
    parent_item = next(i for i in parent_session["items"] if i["id"] == 2)
    assert parent_item["status"] == "pending"
    assert parent_item["blocker"] is None
    assert parent_item["child_session_resolution"] == "Nested work finished"


def test_complete_child_session_requires_parent_metadata(sessions_dir):
    sf = sessions_dir / "session_20260314_201500.json"
    create_session(sf, [{"title": "Standalone", "status": "completed"}])
    with pytest.raises(ValueError, match="not a child session"):
        complete_child_session(sf)


def test_complete_child_session_invalid_disposition_raises(session_file, sessions_dir):
    child_sf = sessions_dir / "session_20260314_202000.json"
    create_child_session(
        session_file, child_sf, [{"title": "T"}], parent_item_id=2,
    )
    with pytest.raises(ValueError, match="Invalid disposition"):
        complete_child_session(child_sf, disposition="skipped")


def test_complete_child_session_cancelled_does_not_require_all_items_done(
    session_file, sessions_dir
):
    child_sf = sessions_dir / "session_20260314_202100.json"
    create_child_session(
        session_file, child_sf, [{"title": "Open task"}], parent_item_id=2,
    )
    # Do NOT mark any items done — cancellation should still succeed
    result = complete_child_session(child_sf, disposition="cancelled")
    child_session = result["child_session"]
    assert child_session["status"] == "cancelled"


def test_complete_child_session_cancelled_unblocks_parent_item(
    session_file, sessions_dir
):
    child_sf = sessions_dir / "session_20260314_202200.json"
    create_child_session(
        session_file, child_sf, [{"title": "T"}], parent_item_id=2,
    )
    result = complete_child_session(child_sf, disposition="cancelled")
    parent_session = result["parent_session"]
    assert parent_session["active_child_session"] is None
    parent_item = next(i for i in parent_session["items"] if i["id"] == 2)
    assert parent_item["status"] == "pending"
    assert parent_item["blocker"] is None


def test_complete_child_session_cancelled_stores_default_resolution_note(
    session_file, sessions_dir
):
    child_sf = sessions_dir / "session_20260314_202300.json"
    create_child_session(
        session_file, child_sf, [{"title": "T"}], parent_item_id=2,
    )
    result = complete_child_session(child_sf, disposition="cancelled")
    parent_item = next(
        i for i in result["parent_session"]["items"] if i["id"] == 2
    )
    assert "cancelled" in parent_item["child_session_resolution"].lower()


def test_complete_child_session_cancelled_uses_resolution_as_note(
    session_file, sessions_dir
):
    child_sf = sessions_dir / "session_20260314_202400.json"
    create_child_session(
        session_file, child_sf, [{"title": "T"}], parent_item_id=2,
    )
    result = complete_child_session(
        child_sf, resolution="superseded by new approach", disposition="cancelled"
    )
    parent_item = next(
        i for i in result["parent_session"]["items"] if i["id"] == 2
    )
    assert parent_item["child_session_resolution"] == "superseded by new approach"


def test_complete_child_session_cancelled_stores_reason_on_child(
    session_file, sessions_dir
):
    child_sf = sessions_dir / "session_20260314_202500.json"
    create_child_session(
        session_file, child_sf, [{"title": "T"}], parent_item_id=2,
    )
    result = complete_child_session(
        child_sf, resolution="no longer needed", disposition="cancelled"
    )
    assert result["child_session"].get("cancel_reason") == "no longer needed"


# ---------------------------------------------------------------------------
# obo_sessions_dir / resolve_session_file
# ---------------------------------------------------------------------------

def test_obo_sessions_dir(tmp_path):
    result = obo_sessions_dir(tmp_path)
    assert result == tmp_path / ".github" / "obo_sessions"


def test_resolve_session_file_absolute(tmp_path):
    abs_path = tmp_path / "session_20260314_120000.json"
    result = resolve_session_file(abs_path)
    assert result == abs_path.resolve()


def test_resolve_session_file_relative_with_base(tmp_path):
    base = tmp_path
    result = resolve_session_file(
        "session_20260314_120000.json",
        base_dir=base,
    )
    expected = (
        tmp_path
        / ".github"
        / "obo_sessions"
        / "session_20260314_120000.json"
    ).resolve()
    assert result == expected


def test_resolve_session_file_relative_no_base():
    with pytest.raises(ValueError, match="no base_dir was provided"):
        resolve_session_file("session_20260314_120000.json")


def test_validate_session_filename_accepts_conforming_name():
    assert (
        validate_session_filename("session_20260314_120000.json")
        == "session_20260314_120000.json"
    )


def test_validate_session_filename_rejects_nonconforming_name():
    with pytest.raises(ValueError, match="Invalid session filename"):
        validate_session_filename("session_12345.json")


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------

def test_get_item_found(session_file):
    item = get_item(session_file, 1)
    assert item is not None
    assert item["id"] == 1
    assert item["title"] == "Alpha"


def test_get_item_not_found(session_file):
    item = get_item(session_file, 999)
    assert item is None


def test_get_item_string_id(session_file):
    item = get_item(session_file, "2")
    assert item is not None
    assert item["id"] == 2


def test_complete_session_raises_with_actionable_items(session_file):
    with pytest.raises(
        ValueError,
        match="pending, in_progress, deferred, or blocked",
    ):
        complete_session(session_file)


def test_complete_session_succeeds_when_done(sessions_dir):
    sf = sessions_dir / "session_20260314_196000.json"
    create_session(
        sf,
        [{"title": "Done", "status": "completed"}],
        title="Finished",
    )
    session = complete_session(sf)
    assert session["status"] == "completed"
    assert session["completed_at"]


def test_merge_items_appends_and_reopens_completed_session(sessions_dir):
    sf = sessions_dir / "session_20260314_197000.json"
    create_session(sf, [{"title": "Initial"}], title="Merge Test")
    mark_complete(sf, 1, "done")

    result = merge_items(sf, [{"title": "Follow-up"}])
    session = result["session"]
    assert session["status"] == "active"
    assert len(result["merged_items"]) == 1
    assert len(session["items"]) == 2
    assert session["items"][-1]["id"] == 2


def test_merge_items_rejects_duplicate_ids(sessions_dir):
    sf = sessions_dir / "session_20260314_198000.json"
    create_session(
        sf,
        [{"id": "phase-1", "title": "Initial"}],
        title="Dup Test",
    )
    with pytest.raises(ValueError, match="Duplicate item id"):
        merge_items(sf, [{"id": "phase-1", "title": "Conflict"}])


# ---------------------------------------------------------------------------
# _is_valid_index
# ---------------------------------------------------------------------------

def test_is_valid_index_good():
    assert _is_valid_index({"format_version": 1, "sessions": []}) is True


def test_is_valid_index_wrong_version():
    assert _is_valid_index({"format_version": 2, "sessions": []}) is False


def test_is_valid_index_sessions_not_list():
    assert _is_valid_index({"format_version": 1, "sessions": {}}) is False


def test_is_valid_index_not_dict():
    assert _is_valid_index([]) is False
    assert _is_valid_index("corrupt") is False
    assert _is_valid_index(None) is False


def test_is_valid_index_missing_sessions_key():
    assert _is_valid_index({"format_version": 1}) is False


# ---------------------------------------------------------------------------
# _rebuild_index_from_files
# ---------------------------------------------------------------------------

def test_rebuild_index_from_files(sessions_dir, session_file):
    rebuilt = _rebuild_index_from_files(sessions_dir)
    assert rebuilt["format_version"] == 1
    assert isinstance(rebuilt["sessions"], list)
    assert any(s["file"] == session_file.name for s in rebuilt["sessions"])


def test_rebuild_index_from_files_empty_dir(sessions_dir):
    rebuilt = _rebuild_index_from_files(sessions_dir)
    assert rebuilt["sessions"] == []


def test_rebuild_index_marks_unreadable_files(sessions_dir):
    bad_file = sessions_dir / "session_20260314_999999.json"
    bad_file.write_text("this is not valid json{{{{")
    rebuilt = _rebuild_index_from_files(sessions_dir)
    entry = next(s for s in rebuilt["sessions"] if s["file"] == bad_file.name)
    assert entry["status"] == "unreadable"


# ---------------------------------------------------------------------------
# Corrupt index.json → auto-repair via list_sessions
# ---------------------------------------------------------------------------

def test_list_sessions_corrupt_json_triggers_rebuild(
    sessions_dir,
    session_file,
):
    """Corrupt JSON in index.json should trigger a full rebuild."""
    idx_path = sessions_dir / "index.json"
    idx_path.write_text("{ this is not valid json }")
    rows = list_sessions(sessions_dir)
    assert any(r["file"] == session_file.name for r in rows)
    # Index should be repaired on disk
    repaired = json.loads(idx_path.read_text())
    assert repaired["format_version"] == 1
    assert any(s["file"] == session_file.name for s in repaired["sessions"])


def test_list_sessions_wrong_format_version_triggers_rebuild(
    sessions_dir,
    session_file,
):
    """An index with an unsupported format_version should trigger a rebuild."""
    idx_path = sessions_dir / "index.json"
    idx_path.write_text(json.dumps({
        "format_version": 99,
        "last_updated": "",
        "sessions": [],
    }))
    rows = list_sessions(sessions_dir)
    assert any(r["file"] == session_file.name for r in rows)
    repaired = json.loads(idx_path.read_text())
    assert repaired["format_version"] == 1


def test_list_sessions_wrong_structure_triggers_rebuild(
    sessions_dir,
    session_file,
):
    """An index whose sessions key is not a list should trigger a rebuild."""
    idx_path = sessions_dir / "index.json"
    idx_path.write_text(json.dumps({
        "format_version": 1,
        "last_updated": "",
        "sessions": "not-a-list",
    }))
    rows = list_sessions(sessions_dir)
    assert any(r["file"] == session_file.name for r in rows)


def test_list_sessions_index_not_a_dict_triggers_rebuild(
    sessions_dir,
    session_file,
):
    """A JSON-array index instead of an object should trigger rebuild."""
    idx_path = sessions_dir / "index.json"
    idx_path.write_text(json.dumps([{"format_version": 1}]))
    rows = list_sessions(sessions_dir)
    assert any(r["file"] == session_file.name for r in rows)


# ---------------------------------------------------------------------------
# Corrupt index.json -> auto-repair via _upsert_index,
# called from mark_complete.
# ---------------------------------------------------------------------------

def test_upsert_preserves_other_sessions_when_index_corrupt(
    sessions_dir,
    sample_items,
):
    """mark_complete on one session must not erase other sessions."""
    sf1 = sessions_dir / "session_20260314_120000.json"
    sf2 = sessions_dir / "session_20260314_130000.json"
    create_session(sf1, sample_items, title="Session A")
    create_session(sf2, sample_items, title="Session B")

    # Corrupt the index
    (sessions_dir / "index.json").write_text("CORRUPT")

    # An operation on sf1 should repair the index and keep sf2
    mark_complete(sf1, 1, "done")

    idx = json.loads((sessions_dir / "index.json").read_text())
    files = [s["file"] for s in idx["sessions"]]
    assert sf1.name in files
    assert sf2.name in files


def test_upsert_repairs_wrong_format_version(sessions_dir, sample_items):
    """_upsert_index must recover if format_version is unsupported."""
    sf1 = sessions_dir / "session_20260314_120000.json"
    create_session(sf1, sample_items, title="Session A")

    # Overwrite index with wrong version
    (sessions_dir / "index.json").write_text(json.dumps({
        "format_version": 99,
        "last_updated": "",
        "sessions": [],
    }))

    mark_skip(sf1, 1, "skipping")

    idx = json.loads((sessions_dir / "index.json").read_text())
    assert idx["format_version"] == 1
    assert any(s["file"] == sf1.name for s in idx["sessions"])


# ---------------------------------------------------------------------------
# cancel_session
# ---------------------------------------------------------------------------

def test_cancel_session_sets_status(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_120000.json"
    create_session(sf, sample_items, title="To cancel")
    session = cancel_session(sf)
    assert session["status"] == "cancelled"


def test_cancel_session_stores_cancelled_at(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_120001.json"
    create_session(sf, sample_items, title="To cancel 2")
    session = cancel_session(sf)
    assert "cancelled_at" in session
    assert session["cancelled_at"]  # non-empty string


def test_cancel_session_stores_reason(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_120002.json"
    create_session(sf, sample_items, title="To cancel 3")
    session = cancel_session(sf, reason="superseded")
    assert session.get("cancel_reason") == "superseded"


def test_cancel_session_no_reason(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_120003.json"
    create_session(sf, sample_items, title="To cancel 4")
    session = cancel_session(sf)
    assert session.get("cancel_reason", "") == ""


def test_cancel_session_updates_index(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_120004.json"
    create_session(sf, sample_items, title="To cancel 5")
    cancel_session(sf)
    rows = list_sessions(sessions_dir, status_filter="cancelled")
    assert any(r["file"] == sf.name for r in rows)


def test_cancel_session_open_items_preserved(sessions_dir, sample_items):
    """Cancelling a session must not alter item statuses."""
    sf = sessions_dir / "session_20260314_120005.json"
    create_session(sf, sample_items, title="Cancel with open items")
    session = cancel_session(sf)
    open_items = [i for i in session["items"] if i["status"] == "pending"]
    assert len(open_items) == len(sample_items)


def test_sync_status_preserves_cancelled(sessions_dir, sample_items):
    """_sync_session_status must not reactivate a cancelled session."""
    from oboe_mcp.session import _sync_session_status
    sf = sessions_dir / "session_20260314_120006.json"
    create_session(sf, sample_items, title="Cancelled check")
    session = cancel_session(sf)
    status_before = session["status"]
    _sync_session_status(session)
    assert session["status"] == status_before == "cancelled"


# ---------------------------------------------------------------------------
# trim_sessions
# ---------------------------------------------------------------------------

def test_trim_sessions_deletes_completed(sessions_dir, sample_items):
    sf1 = sessions_dir / "session_20260314_120000.json"
    sf2 = sessions_dir / "session_20260314_130000.json"
    # Create sf1 with a pre-completed item so _sync_session_status marks it completed
    create_session(sf1, [{"title": "A", "status": "completed"}], title="Done")
    create_session(sf2, sample_items, title="Active")

    result = trim_sessions(sessions_dir, status_filter="completed")
    assert sf1.name in result["deleted"]
    assert not sf1.exists()
    assert sf2.exists()


def test_trim_sessions_dry_run_does_not_delete(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_120000.json"
    # Pre-completed item so session shows as completed in the index
    create_session(sf, [{"title": "A", "status": "completed"}], title="Done")

    result = trim_sessions(sessions_dir, status_filter="completed", dry_run=True)
    assert result["dry_run"] is True
    assert sf.exists()  # not deleted
    assert sf.name in result["deleted"]


def test_trim_sessions_before_filter(sessions_dir, sample_items):
    import json as _json
    from oboe_mcp.session import _upsert_index
    sf_old = sessions_dir / "session_20260101_000000.json"
    sf_new = sessions_dir / "session_20260314_120000.json"
    # Both sessions created with pre-completed items so they appear completed in index
    create_session(sf_old, [{"title": "A", "status": "completed"}], title="Old")
    create_session(sf_new, [{"title": "B", "status": "completed"}], title="New")
    # Backdate sf_old's created field so it falls before the cutoff
    s_old = _json.loads(sf_old.read_text())
    s_old["created"] = "2026-01-01T00:00:00"
    sf_old.write_text(_json.dumps(s_old))
    _upsert_index(sessions_dir, s_old, sf_old.name)

    # Use a cutoff that includes only sf_old (created 2026-01-01 < 2026-02-01)
    cutoff = "2026-02-01T00:00:00"
    result = trim_sessions(sessions_dir, before=cutoff, status_filter="completed")
    assert sf_old.name in result["deleted"]
    assert sf_new.name not in result["deleted"]
    assert not sf_old.exists()
    assert sf_new.exists()


def test_trim_sessions_before_now_deletes_all_matching(sessions_dir, sample_items):
    sf1 = sessions_dir / "session_20260314_120000.json"
    sf2 = sessions_dir / "session_20260314_130000.json"
    # Pre-completed items so sessions appear completed in index
    create_session(sf1, [{"title": "A", "status": "completed"}], title="Done 1")
    create_session(sf2, [{"title": "B", "status": "completed"}], title="Done 2")

    result = trim_sessions(sessions_dir, before="now", status_filter="completed")
    assert not sf1.exists()
    assert not sf2.exists()
    assert result["total_deleted"] == 2


def test_trim_sessions_status_filter_none_matches_any(sessions_dir, sample_items):
    sf_comp = sessions_dir / "session_20260314_120000.json"
    sf_canc = sessions_dir / "session_20260314_130000.json"
    # Pre-completed item so session appears completed in index
    create_session(sf_comp, [{"title": "A", "status": "completed"}], title="Completed")
    create_session(sf_canc, sample_items, title="Cancelled")
    cancel_session(sf_canc)

    result = trim_sessions(sessions_dir, before="now", status_filter=None)
    assert result["total_deleted"] == 2


def test_trim_sessions_rebuilds_index(sessions_dir, sample_items):
    sf = sessions_dir / "session_20260314_120000.json"
    sf2 = sessions_dir / "session_20260314_130000.json"
    # Pre-completed item so session appears completed in index
    create_session(sf, [{"title": "A", "status": "completed"}], title="Done")
    create_session(sf2, sample_items, title="Kept")

    trim_sessions(sessions_dir, status_filter="completed")
    rows = list_sessions(sessions_dir)
    assert not any(r["file"] == sf.name for r in rows)
    assert any(r["file"] == sf2.name for r in rows)
