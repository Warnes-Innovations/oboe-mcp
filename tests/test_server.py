"""Integration tests for MCP tool handlers in server.py."""

import json
import pytest
from pathlib import Path

from obo_mcp.server import (
    obo_create,
    obo_get_item,
    obo_list_items,
    obo_list_sessions,
    obo_mark_complete,
    obo_mark_skip,
    obo_next,
    obo_session_status,
    obo_update_field,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ITEMS = [
    {"title": "Alpha", "urgency": 5, "importance": 4, "effort": 2, "dependencies": 3},
    {"title": "Beta",  "urgency": 2, "importance": 3, "effort": 4, "dependencies": 1},
    {"title": "Gamma", "urgency": 3, "importance": 3, "effort": 3, "dependencies": 1},
]


@pytest.fixture
def base_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def session_name(base_dir):
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


def test_obo_create_updates_index(base_dir):
    obo_create(
        base_dir=base_dir,
        title="Indexed",
        description="",
        items=SAMPLE_ITEMS,
        session_filename="session_20260314_140000.json",
    )
    from obo_mcp.session import obo_sessions_dir, load_index
    idx = load_index(obo_sessions_dir(base_dir))
    assert any(s["file"] == "session_20260314_140000.json" for s in idx["sessions"])


def test_obo_create_duplicate_returns_error(base_dir, session_name):
    result = obo_create(
        base_dir=base_dir,
        title="Dup",
        description="",
        items=SAMPLE_ITEMS,
        session_filename=session_name,
    )
    assert result.startswith("ERROR:")


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
    assert data["completed"] == 0


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
    result = obo_next(session_file="session_20260314_150000.json", base_dir=base_dir)
    data = json.loads(result)
    assert "message" in data


# ---------------------------------------------------------------------------
# obo_list_items
# ---------------------------------------------------------------------------

def test_obo_list_items_sorted(base_dir, session_name):
    result = obo_list_items(session_file=session_name, base_dir=base_dir)
    data = json.loads(result)
    scores = [i["priority_score"] for i in data["items"]]
    assert scores == sorted(scores, reverse=True)


def test_obo_list_items_filter(base_dir, session_name):
    obo_mark_complete(session_file=session_name, item_id="1", resolution="Done", base_dir=base_dir)
    result = obo_list_items(session_file=session_name, base_dir=base_dir, status_filter="completed")
    data = json.loads(result)
    assert data["total"] == 1


# ---------------------------------------------------------------------------
# obo_get_item
# ---------------------------------------------------------------------------

def test_obo_get_item(base_dir, session_name):
    result = obo_get_item(session_file=session_name, item_id="1", base_dir=base_dir)
    data = json.loads(result)
    assert data["title"] == "Alpha"


def test_obo_get_item_not_found(base_dir, session_name):
    result = obo_get_item(session_file=session_name, item_id="999", base_dir=base_dir)
    assert result.startswith("ERROR:")


# ---------------------------------------------------------------------------
# obo_mark_complete
# ---------------------------------------------------------------------------

def test_obo_mark_complete(base_dir, session_name):
    result = obo_mark_complete(session_file=session_name, item_id="1", resolution="Fixed", base_dir=base_dir)
    data = json.loads(result)
    assert data["action"] == "completed"
    assert data["resolution"] == "Fixed"
    assert data["progress"] == "1/3"


def test_obo_mark_complete_unknown_id(base_dir, session_name):
    result = obo_mark_complete(session_file=session_name, item_id="999", resolution="?", base_dir=base_dir)
    assert result.startswith("ERROR:")


# ---------------------------------------------------------------------------
# obo_mark_skip
# ---------------------------------------------------------------------------

def test_obo_mark_skip(base_dir, session_name):
    result = obo_mark_skip(session_file=session_name, item_id="2", reason="Not applicable", base_dir=base_dir)
    data = json.loads(result)
    assert data["action"] == "skipped"
    assert data["total_skipped"] == 1


def test_obo_mark_skip_no_reason(base_dir, session_name):
    result = obo_mark_skip(session_file=session_name, item_id="3", base_dir=base_dir)
    data = json.loads(result)
    assert data["action"] == "skipped"


# ---------------------------------------------------------------------------
# obo_update_field
# ---------------------------------------------------------------------------

def test_obo_update_field_score_recalculates(base_dir, session_name):
    result = obo_update_field(
        session_file=session_name, item_id="1", field="urgency", value="1", base_dir=base_dir
    )
    data = json.loads(result)
    # urgency=1, importance=4, effort=2, dependencies=3 → 1+4+4+3 = 12
    assert data["priority_score"] == 12


def test_obo_update_field_non_score(base_dir, session_name):
    result = obo_update_field(
        session_file=session_name, item_id="1", field="title", value="Renamed", base_dir=base_dir
    )
    data = json.loads(result)
    assert data["new_value"] == "Renamed"
    assert "priority_score" not in data


def test_obo_update_field_unknown_id(base_dir, session_name):
    result = obo_update_field(
        session_file=session_name, item_id="999", field="title", value="Ghost", base_dir=base_dir
    )
    assert result.startswith("ERROR:")
