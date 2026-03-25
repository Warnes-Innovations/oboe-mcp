# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Integration tests for MCP tool handlers in server.py."""

# mypy: disable-error-code=import-untyped

import json
import pytest

from oboe_mcp.server import (
    obo_complete_child_session,
    obo_complete_session,
    obo_create,
    obo_create_child_session,
    obo_get_item,
    obo_list_items,
    obo_list_sessions,
    obo_mark_blocked,
    obo_mark_complete,
    obo_mark_in_progress,
    obo_mark_skip,
    obo_merge_items,
    obo_next,
    obo_set_approval,
    obo_session_status,
    obo_update_field,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ITEMS = [
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


@pytest.fixture
def _base_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture(name="base_dir")
def fixture_base_dir(_base_dir):
    return _base_dir


@pytest.fixture(name="session_name")
def fixture_session_name(base_dir):
    result = obo_create(
        base_dir=base_dir,
        title="Test Session",
        description="Integration test",
        items=SAMPLE_ITEMS,
        session_filename="session_20260314_120000.json",
    )
    data = json.loads(result)
    return data["session_file"]


# ---------------------------------------------------------------------------
# obo_create
# ---------------------------------------------------------------------------

def test_obo_create_returns_metadata(base_dir):
    result = obo_create(
        base_dir=base_dir,
        title="My Session",
        description="desc",
        items=SAMPLE_ITEMS,
        session_filename="session_20260314_130000.json",
    )
    data = json.loads(result)
    assert data["items_created"] == 3
    assert data["status"] == "active"
    assert data["session_file"] == "session_20260314_130000.json"


def test_obo_create_returns_completed_status_when_all_items_done(base_dir):
    result = obo_create(
        base_dir=base_dir,
        title="Finished Session",
        description="desc",
        items=[{"title": "Done", "status": "completed"}],
        session_filename="session_20260314_130500.json",
    )
    data = json.loads(result)
    assert data["status"] == "completed"


def test_obo_create_updates_index(base_dir):
    obo_create(
        base_dir=base_dir,
        title="Indexed",
        description="",
        items=SAMPLE_ITEMS,
        session_filename="session_20260314_140000.json",
    )
    from oboe_mcp.session import obo_sessions_dir, load_index

    idx = load_index(obo_sessions_dir(base_dir))
    assert any(
        s["file"] == "session_20260314_140000.json"
        for s in idx["sessions"]
    )


def test_obo_create_duplicate_returns_error(base_dir, session_name):
    result = obo_create(
        base_dir=base_dir,
        title="Dup",
        description="",
        items=SAMPLE_ITEMS,
        session_filename=session_name,
    )
    assert result.startswith("ERROR:")


def test_obo_create_rejects_invalid_filename(base_dir):
    result = obo_create(
        base_dir=base_dir,
        title="Bad Filename",
        description="desc",
        items=SAMPLE_ITEMS,
        session_filename="session_bad.json",
    )
    assert result.startswith("ERROR:")


def test_obo_create_without_items_creates_empty_session(base_dir):
    result = obo_create(
        base_dir=base_dir,
        title="Empty Session",
        description="no items yet",
        session_filename="session_20260314_131000.json",
    )
    data = json.loads(result)
    assert data["items_created"] == 0
    assert data["status"] == "completed"


def test_obo_create_with_items_none_creates_empty_session(base_dir):
    result = obo_create(
        base_dir=base_dir,
        title="Empty Session None",
        description="no items yet",
        items=None,
        session_filename="session_20260314_131500.json",
    )
    data = json.loads(result)
    assert data["items_created"] == 0


# ---------------------------------------------------------------------------
# obo_list_sessions
# ---------------------------------------------------------------------------

def test_obo_list_sessions(base_dir, session_name):
    result = obo_list_sessions(base_dir=base_dir)
    data = json.loads(result)
    assert data["total"] == 1
    assert data["sessions"][0]["file"] == session_name


def test_obo_list_sessions_empty(tmp_path):
    result = obo_list_sessions(base_dir=str(tmp_path))
    data = json.loads(result)
    assert data["sessions"] == []


# ---------------------------------------------------------------------------
# obo_session_status
# ---------------------------------------------------------------------------

def test_obo_session_status(base_dir, session_name):
    result = obo_session_status(session_file=session_name, base_dir=base_dir)
    data = json.loads(result)
    assert data["total"] == 3
    assert data["pending"] == 3
    assert data["deferred"] == 0
    assert data["completed"] == 0
    assert data["approval"]["unreviewed"] == 3


# ---------------------------------------------------------------------------
# obo_next
# ---------------------------------------------------------------------------

def test_obo_next_returns_highest_priority(base_dir, session_name):
    result = obo_next(session_file=session_name, base_dir=base_dir)
    data = json.loads(result)
    assert data["title"] == "Alpha"


def test_obo_next_no_items(base_dir):
    obo_create(
        base_dir=base_dir,
        title="Empty",
        description="",
        items=[{"title": "Done", "status": "completed"}],
        session_filename="session_20260314_150000.json",
    )
    result = obo_next(
        session_file="session_20260314_150000.json",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert "message" in data


def test_obo_next_returns_deferred_when_review_queue_is_exhausted(base_dir):
    obo_create(
        base_dir=base_dir,
        title="Deferred",
        description="",
        items=[
            {
                "title": "Later",
                "status": "deferred",
                "approval_status": "approved",
                "approval_mode": "delayed",
            }
        ],
        session_filename="session_20260314_150500.json",
    )
    result = obo_next(
        session_file="session_20260314_150500.json",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["status"] == "deferred"
    assert data["approval_status"] == "approved"


# ---------------------------------------------------------------------------
# obo_list_items
# ---------------------------------------------------------------------------

def test_obo_list_items_sorted(base_dir, session_name):
    result = obo_list_items(session_file=session_name, base_dir=base_dir)
    data = json.loads(result)
    scores = [i["priority_score"] for i in data["items"]]
    assert scores == sorted(scores, reverse=True)


def test_obo_list_items_filter(base_dir, session_name):
    obo_mark_complete(
        session_file=session_name,
        item_id="1",
        resolution="Done",
        base_dir=base_dir,
    )
    result = obo_list_items(
        session_file=session_name,
        base_dir=base_dir,
        status_filter="completed",
    )
    data = json.loads(result)
    assert data["total"] == 1


# ---------------------------------------------------------------------------
# obo_get_item
# ---------------------------------------------------------------------------

def test_obo_get_item(base_dir, session_name):
    result = obo_get_item(
        session_file=session_name,
        item_id="1",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["title"] == "Alpha"


def test_obo_get_item_not_found(base_dir, session_name):
    result = obo_get_item(
        session_file=session_name,
        item_id="999",
        base_dir=base_dir,
    )
    assert result.startswith("ERROR:")


# ---------------------------------------------------------------------------
# obo_mark_complete
# ---------------------------------------------------------------------------

def test_obo_mark_complete(base_dir, session_name):
    result = obo_mark_complete(
        session_file=session_name,
        item_id="1",
        resolution="Fixed",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["action"] == "completed"
    assert data["resolution"] == "Fixed"
    assert data["progress"] == "1/3"


def test_obo_mark_complete_unknown_id(base_dir, session_name):
    result = obo_mark_complete(
        session_file=session_name,
        item_id="999",
        resolution="?",
        base_dir=base_dir,
    )
    assert result.startswith("ERROR:")


# ---------------------------------------------------------------------------
# obo_mark_skip
# ---------------------------------------------------------------------------

def test_obo_mark_skip(base_dir, session_name):
    result = obo_mark_skip(
        session_file=session_name,
        item_id="2",
        reason="Not applicable",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["action"] == "skipped"
    assert data["total_skipped"] == 1


def test_obo_mark_skip_no_reason(base_dir, session_name):
    result = obo_mark_skip(
        session_file=session_name,
        item_id="3",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["action"] == "skipped"


def test_obo_mark_blocked(base_dir, session_name):
    result = obo_mark_blocked(
        session_file=session_name,
        item_id="2",
        blocker="Waiting on product decision",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["action"] == "blocked"
    assert data["blocker"] == {"summary": "Waiting on product decision"}
    assert data["total_blocked"] == 1


def test_obo_mark_in_progress(base_dir, session_name):
    result = obo_mark_in_progress(
        session_file=session_name,
        item_id="2",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["action"] == "in_progress"
    assert data["total_in_progress"] == 1


# ---------------------------------------------------------------------------
# obo_update_field
# ---------------------------------------------------------------------------

def test_obo_update_field_score_recalculates(base_dir, session_name):
    result = obo_update_field(
        session_file=session_name,
        item_id="1",
        field="urgency",
        value="1",
        base_dir=base_dir,
    )
    data = json.loads(result)
    # urgency=1, importance=4, effort=2, dependencies=3 → 1+4+4+3 = 12
    assert data["priority_score"] == 12


def test_obo_update_field_non_score(base_dir, session_name):
    result = obo_update_field(
        session_file=session_name,
        item_id="1",
        field="title",
        value="Renamed",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["new_value"] == "Renamed"
    assert "priority_score" not in data


def test_obo_update_field_approval_mode(base_dir, session_name):
    result = obo_update_field(
        session_file=session_name,
        item_id="1",
        field="approval_mode",
        value="delayed",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["new_value"] == "delayed"


def test_obo_set_approval_defaults_to_immediate(base_dir, session_name):
    result = obo_set_approval(
        session_file=session_name,
        item_id="1",
        approval_status="approved",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["action"] == "approval_updated"
    assert data["approval_status"] == "approved"
    assert data["approval_mode"] == "immediate"
    assert data["lifecycle_status"] == "pending"


def test_obo_set_approval_delayed_sets_deferred(base_dir, session_name):
    result = obo_set_approval(
        session_file=session_name,
        item_id="1",
        approval_status="approved",
        approval_mode="delayed",
        note="Implement after review",
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["approval_mode"] == "delayed"
    assert data["lifecycle_status"] == "deferred"
    assert data["approval_note"] == "Implement after review"


def test_obo_set_approval_rejects_invalid_combination(base_dir, session_name):
    result = obo_set_approval(
        session_file=session_name,
        item_id="1",
        approval_status="denied",
        approval_mode="delayed",
        base_dir=base_dir,
    )
    assert result.startswith("ERROR:")


def test_obo_update_field_rejects_invalid_approval_mode(
    base_dir,
    session_name,
):
    result = obo_update_field(
        session_file=session_name,
        item_id="1",
        field="approval_mode",
        value="soon",
        base_dir=base_dir,
    )
    assert result.startswith("ERROR:")


def test_obo_update_field_unknown_id(base_dir, session_name):
    result = obo_update_field(
        session_file=session_name,
        item_id="999",
        field="title",
        value="Ghost",
        base_dir=base_dir,
    )
    assert result.startswith("ERROR:")


def test_obo_update_field_rejects_invalid_status(base_dir, session_name):
    result = obo_update_field(
        session_file=session_name,
        item_id="1",
        field="status",
        value="stalled",
        base_dir=base_dir,
    )
    assert result.startswith("ERROR:")


def test_obo_complete_session_rejects_actionable_items(base_dir, session_name):
    result = obo_complete_session(session_file=session_name, base_dir=base_dir)
    assert result.startswith("ERROR:")


def test_obo_complete_session(base_dir):
    result = obo_create(
        base_dir=base_dir,
        title="Finished",
        description="done",
        items=[{"title": "Done", "status": "completed"}],
        session_filename="session_20260314_160000.json",
    )
    created_session_name = json.loads(result)["session_file"]
    complete_result = obo_complete_session(
        session_file=created_session_name,
        base_dir=base_dir,
    )
    data = json.loads(complete_result)
    assert data["action"] == "session_completed"
    assert data["session_status"] == "completed"


def test_obo_merge_items(base_dir, session_name):
    result = obo_merge_items(
        session_file=session_name,
        items=[{"title": "Delta"}],
        base_dir=base_dir,
    )
    data = json.loads(result)
    assert data["action"] == "merged"
    assert data["merged_count"] == 1
    assert data["total_items"] == 4


def test_obo_create_child_session(base_dir, session_name):
    result = obo_create_child_session(
        parent_session_file=session_name,
        title="Nested Investigation",
        description="child flow",
        items=[{"title": "Child item"}],
        base_dir=base_dir,
        parent_item_id="2",
        session_filename="session_20260314_165000.json",
    )
    data = json.loads(result)
    assert data["action"] == "child_created"
    assert data["parent_status"] == "paused"
    assert data["child_session_file"] == "session_20260314_165000.json"


def test_obo_create_child_session_without_items(base_dir, session_name):
    result = obo_create_child_session(
        parent_session_file=session_name,
        title="Empty Child",
        description="child with no initial items",
        base_dir=base_dir,
        session_filename="session_20260314_165100.json",
    )
    data = json.loads(result)
    assert data["action"] == "child_created"
    assert data["parent_status"] == "paused"


def test_obo_complete_child_session(base_dir, session_name):
    create_result = obo_create_child_session(
        parent_session_file=session_name,
        title="Nested Investigation",
        description="child flow",
        items=[{"title": "Child item"}],
        base_dir=base_dir,
        parent_item_id="2",
        session_filename="session_20260314_165500.json",
    )
    child_session_name = json.loads(create_result)["child_session_file"]

    complete_item_result = obo_mark_complete(
        session_file=child_session_name,
        item_id="1",
        resolution="Child done",
        base_dir=base_dir,
    )
    assert json.loads(complete_item_result)["action"] == "completed"

    result = obo_complete_child_session(
        child_session_file=child_session_name,
        base_dir=base_dir,
        resolution="Nested work complete",
    )
    data = json.loads(result)
    assert data["action"] == "child_completed"
    assert data["child_status"] == "completed"
    assert data["parent_status"] == "active"
    assert data["active_child_session"] is None


def test_obo_end_to_end_agent_workflow(base_dir):
    create_result = obo_create(
        base_dir=base_dir,
        title="Workflow Session",
        description="agent flow",
        items=[
            {
                "id": "phase-1",
                "title": "Design",
                "urgency": 5,
                "importance": 5,
                "effort": 2,
                "dependencies": 2,
            },
            {
                "id": "phase-2",
                "title": "Build",
                "urgency": 3,
                "importance": 4,
                "effort": 3,
                "dependencies": 1,
            },
        ],
        session_filename="session_20260314_170000.json",
    )
    created_session_name = json.loads(create_result)["session_file"]

    next_result = obo_next(
        session_file=created_session_name,
        base_dir=base_dir,
    )
    assert json.loads(next_result)["id"] == "phase-1"

    in_progress_result = obo_mark_in_progress(
        session_file=created_session_name,
        item_id="phase-1",
        base_dir=base_dir,
    )
    assert json.loads(in_progress_result)["action"] == "in_progress"

    resumed_result = obo_next(
        session_file=created_session_name,
        base_dir=base_dir,
    )
    assert json.loads(resumed_result)["id"] == "phase-1"

    merge_result = obo_merge_items(
        session_file=created_session_name,
        items=[{"id": "phase-3", "title": "Verify"}],
        base_dir=base_dir,
    )
    assert json.loads(merge_result)["merged_count"] == 1

    blocked_result = obo_mark_blocked(
        session_file=created_session_name,
        item_id="phase-2",
        blocker="Waiting on design sign-off",
        base_dir=base_dir,
    )
    assert json.loads(blocked_result)["action"] == "blocked"

    child_result = obo_create_child_session(
        parent_session_file=created_session_name,
        title="Design Sign-off",
        description="resolve external blocker",
        items=[{"title": "Get approval"}],
        base_dir=base_dir,
        session_filename="session_20260314_170500.json",
    )
    child_session_name = json.loads(child_result)["child_session_file"]

    paused_parent_next = obo_next(
        session_file=created_session_name,
        base_dir=base_dir,
    )
    assert paused_parent_next.startswith("ERROR:")

    child_item_complete = obo_mark_complete(
        session_file=child_session_name,
        item_id="1",
        resolution="Approval received",
        base_dir=base_dir,
    )
    assert json.loads(child_item_complete)["action"] == "completed"

    child_close_result = obo_complete_child_session(
        child_session_file=child_session_name,
        base_dir=base_dir,
        resolution="Approval path resolved",
    )
    assert json.loads(child_close_result)["action"] == "child_completed"

    assert obo_complete_session(
        session_file=created_session_name,
        base_dir=base_dir,
    ).startswith("ERROR:")

    complete_result = obo_mark_complete(
        session_file=created_session_name,
        item_id="phase-1",
        resolution="Design done",
        base_dir=base_dir,
    )
    assert json.loads(complete_result)["action"] == "completed"

    delayed_approval_result = obo_set_approval(
        session_file=created_session_name,
        item_id="phase-2",
        approval_status="approved",
        approval_mode="delayed",
        base_dir=base_dir,
    )
    delayed_data = json.loads(delayed_approval_result)
    assert delayed_data["approval_mode"] == "delayed"
    assert delayed_data["lifecycle_status"] == "deferred"

    final_complete_result = obo_mark_complete(
        session_file=created_session_name,
        item_id="phase-3",
        resolution="Verified",
        base_dir=base_dir,
    )
    assert json.loads(final_complete_result)["action"] == "completed"

    deferred_next_result = obo_next(
        session_file=created_session_name,
        base_dir=base_dir,
    )
    assert json.loads(deferred_next_result)["id"] == "phase-2"

    finish_deferred_result = obo_mark_complete(
        session_file=created_session_name,
        item_id="phase-2",
        resolution="Built after review",
        base_dir=base_dir,
    )
    assert json.loads(finish_deferred_result)["action"] == "completed"

    status_result = obo_session_status(
        session_file=created_session_name,
        base_dir=base_dir,
    )
    status_data = json.loads(status_result)
    assert status_data["status"] == "completed"
    assert status_data["completed"] == 3
    assert status_data["skipped"] == 0
    assert status_data["pending"] == 0
    assert status_data["in_progress"] == 0
    assert status_data["approval"]["approved"] == 1

    close_result = obo_complete_session(
        session_file=created_session_name,
        base_dir=base_dir,
    )
    close_data = json.loads(close_result)
    assert close_data["action"] == "session_completed"
    assert close_data["session_status"] == "completed"

    sessions_result = obo_list_sessions(
        base_dir=base_dir,
        status_filter="completed",
    )
    sessions_data = json.loads(sessions_result)
    assert sessions_data["total"] == 2
    assert any(
        session["file"] == created_session_name
        for session in sessions_data["sessions"]
    )
