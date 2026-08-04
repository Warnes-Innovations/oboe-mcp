# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Regression tests for score-component validation (issue #20).

Passing a non-numeric ``dependencies`` (or any other score component) used to
reach the ``priority_score`` arithmetic unchecked and raise an
interpreter-level ``TypeError`` — ``unsupported operand type(s) for +: 'int'
and 'str'`` — which names neither the offending item nor the offending field.

Every entry point that accepts caller-supplied score components is covered
here: ``create_session`` / ``oboe_create``, ``merge_items`` /
``oboe_merge_items``, ``create_child_session`` /
``oboe_create_child_session``, and ``update_field`` / ``oboe_update_field``.
"""

import json

import pytest

from oboe_mcp.server import (
    oboe_create,
    oboe_create_child_session,
    oboe_merge_items,
    oboe_update_field,
)
from oboe_mcp.session import (
    _recalc_priority,
    create_child_session,
    create_session,
    get_item,
    merge_items,
    update_field,
)

SCORE_COMPONENTS = ("urgency", "importance", "effort", "dependencies")

# The exact payload from the issue report.
REPORTED_ITEM = {
    "id": "example",
    "title": "Example item",
    "description": "...",
    "urgency": 3,
    "importance": 4,
    "effort": 2,
    "dependencies": "Blocks the downstream cutover step",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(name="sessions_dir")
def fixture_sessions_dir(tmp_path):
    d = tmp_path / ".github" / "oboe_sessions"
    d.mkdir(parents=True)
    return d


@pytest.fixture(name="session_file")
def fixture_session_file(sessions_dir):
    sf = sessions_dir / "session_20260314_120000.json"
    create_session(sf, [{"title": "Alpha"}], title="T", description="D")
    return sf


@pytest.fixture(name="base_dir")
def fixture_base_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture(name="session_name")
def fixture_session_name(base_dir):
    result = oboe_create(
        base_dir=base_dir,
        title="Test Session",
        description="d",
        items=[{"title": "Alpha"}],
        session_file="session_20260314_120000.json",
    )
    return json.loads(result)["session_file"]


def assert_names_item_and_field(
    message: str, item_id: object, field: str
) -> None:
    """The error must identify *which* item and *which* field was rejected."""
    assert "unsupported operand" not in message, (
        "raw TypeError surfaced instead of a validation error"
    )
    assert repr(item_id) in message or str(item_id) in message, message
    assert field in message, message


# ---------------------------------------------------------------------------
# Layer 1 — create_session / oboe_create (the exact reported failure)
# ---------------------------------------------------------------------------

def test_create_session_rejects_string_dependencies(sessions_dir):
    """The reproduction from issue #20, at the session-logic layer."""
    sf = sessions_dir / "session_20260314_121000.json"
    with pytest.raises(ValueError) as exc:
        create_session(sf, [dict(REPORTED_ITEM)], title="T", description="D")

    assert_names_item_and_field(str(exc.value), "example", "dependencies")
    assert not sf.exists(), "a rejected session must not be written to disk"


def test_oboe_create_rejects_string_dependencies(base_dir):
    """The reproduction from issue #20, at the MCP tool boundary."""
    result = oboe_create(
        base_dir=base_dir,
        title="My Session",
        description="desc",
        items=[dict(REPORTED_ITEM)],
        session_file="session_20260314_130000.json",
    )
    assert result.startswith("ERROR: "), result
    assert_names_item_and_field(result, "example", "dependencies")


@pytest.mark.parametrize("field", SCORE_COMPONENTS)
def test_create_session_rejects_string_in_any_component(sessions_dir, field):
    sf = sessions_dir / "session_20260314_122000.json"
    item = {"id": "example", "title": "T", field: "not a number"}
    with pytest.raises(ValueError) as exc:
        create_session(sf, [item], title="T", description="D")
    assert_names_item_and_field(str(exc.value), "example", field)


@pytest.mark.parametrize(
    "value", [None, True, False, [], {}, "3", "", 2.5, float("nan")]
)
def test_create_session_rejects_non_integer_values(sessions_dir, value):
    """Booleans, containers, numeric *strings* and fractions are all rejected.

    Numeric strings are rejected here deliberately: the ``oboe_create`` schema
    declares these fields as JSON numbers, and silently coercing ``"3"`` is the
    quiet-default behaviour this issue asks us not to have.
    """
    sf = sessions_dir / "session_20260314_123000.json"
    item = {"id": "example", "title": "T", "dependencies": value}
    with pytest.raises(ValueError) as exc:
        create_session(sf, [item], title="T", description="D")
    assert_names_item_and_field(str(exc.value), "example", "dependencies")


def test_create_session_rejects_out_of_range(sessions_dir):
    sf = sessions_dir / "session_20260314_124000.json"
    item = {"id": "example", "title": "T", "urgency": 42}
    with pytest.raises(ValueError) as exc:
        create_session(sf, [item], title="T", description="D")
    assert_names_item_and_field(str(exc.value), "example", "urgency")


def test_create_session_reports_the_offending_item_not_the_first(sessions_dir):
    """A bad item in the middle of a batch is named, not item 1."""
    sf = sessions_dir / "session_20260314_125000.json"
    items = [
        {"title": "Good"},
        {"id": "bad-one", "title": "Bad", "dependencies": "lots"},
        {"title": "Also good"},
    ]
    with pytest.raises(ValueError) as exc:
        create_session(sf, items, title="T", description="D")
    assert_names_item_and_field(str(exc.value), "bad-one", "dependencies")


def test_create_session_accepts_valid_scores(sessions_dir):
    sf = sessions_dir / "session_20260314_126000.json"
    session = create_session(
        sf,
        [{
            "title": "Fine",
            "urgency": 5,
            "importance": 4,
            "effort": 2,
            "dependencies": 3,
        }],
        title="T",
        description="D",
    )
    assert session["items"][0]["priority_score"] == 5 + 4 + (6 - 2) + 3


def test_create_session_accepts_integral_floats(sessions_dir):
    """JSON has no int/float distinction; ``3.0`` is a valid integer score."""
    sf = sessions_dir / "session_20260314_127000.json"
    session = create_session(
        sf,
        [{"title": "Fine", "urgency": 5.0, "dependencies": 0}],
        title="T",
        description="D",
    )
    item = session["items"][0]
    assert item["urgency"] == 5
    assert isinstance(item["urgency"], int)
    assert item["priority_score"] == 5 + 3 + (6 - 3) + 0


# ---------------------------------------------------------------------------
# Bug-class siblings — merge_items / oboe_merge_items
# ---------------------------------------------------------------------------

def test_merge_items_rejects_string_dependencies(session_file):
    with pytest.raises(ValueError) as exc:
        merge_items(session_file, [dict(REPORTED_ITEM)])
    assert_names_item_and_field(str(exc.value), "example", "dependencies")


def test_merge_items_rejection_leaves_session_unchanged(session_file):
    before = session_file.read_bytes()
    with pytest.raises(ValueError):
        merge_items(session_file, [dict(REPORTED_ITEM)])
    assert session_file.read_bytes() == before


def test_oboe_merge_items_rejects_string_dependencies(base_dir, session_name):
    result = oboe_merge_items(
        session_file=session_name,
        items=[dict(REPORTED_ITEM)],
        base_dir=base_dir,
    )
    assert result.startswith("ERROR: "), result
    assert_names_item_and_field(result, "example", "dependencies")


@pytest.mark.parametrize("field", SCORE_COMPONENTS)
def test_merge_items_rejects_string_in_any_component(session_file, field):
    item = {"id": "example", "title": "T", field: "not a number"}
    with pytest.raises(ValueError) as exc:
        merge_items(session_file, [item])
    assert_names_item_and_field(str(exc.value), "example", field)


# ---------------------------------------------------------------------------
# Bug-class siblings — create_child_session / oboe_create_child_session
# ---------------------------------------------------------------------------

def test_create_child_session_rejects_string_dependencies(
    sessions_dir, session_file
):
    child_sf = sessions_dir / "session_20260314_140000.json"
    with pytest.raises(ValueError) as exc:
        create_child_session(
            session_file,
            child_sf,
            [dict(REPORTED_ITEM)],
            title="Child",
            description="d",
        )
    assert_names_item_and_field(str(exc.value), "example", "dependencies")
    assert not child_sf.exists()


def test_oboe_create_child_session_rejects_string_dependencies(
    base_dir, session_name
):
    result = oboe_create_child_session(
        parent_session_file=session_name,
        title="Child",
        description="d",
        items=[dict(REPORTED_ITEM)],
        base_dir=base_dir,
        session_file="session_20260314_165000.json",
    )
    assert result.startswith("ERROR: "), result
    assert_names_item_and_field(result, "example", "dependencies")


# ---------------------------------------------------------------------------
# Bug-class siblings — update_field / oboe_update_field
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", SCORE_COMPONENTS)
def test_update_field_rejects_non_numeric(session_file, field):
    with pytest.raises(ValueError) as exc:
        update_field(session_file, 1, field, "Blocks the cutover")
    assert_names_item_and_field(str(exc.value), 1, field)


def test_update_field_rejects_out_of_range(session_file):
    with pytest.raises(ValueError) as exc:
        update_field(session_file, 1, "dependencies", "9")
    assert_names_item_and_field(str(exc.value), 1, "dependencies")


def test_update_field_rejects_null_score(session_file):
    with pytest.raises(ValueError) as exc:
        bad: object = None
        update_field(session_file, 1, "urgency", bad)  # type: ignore[arg-type]
    assert_names_item_and_field(str(exc.value), 1, "urgency")


def test_update_field_still_accepts_numeric_strings(session_file):
    """The CLI and the MCP tool both hand ``value`` over as a string."""
    item = update_field(session_file, 1, "urgency", "1")
    assert item["urgency"] == 1
    assert item["priority_score"] == 1 + 3 + (6 - 3) + 1


def test_update_field_rejection_leaves_item_unchanged(session_file):
    before = get_item(session_file, 1)
    with pytest.raises(ValueError):
        update_field(session_file, 1, "dependencies", "many")
    assert get_item(session_file, 1) == before


def test_oboe_update_field_rejects_non_numeric(base_dir, session_name):
    result = oboe_update_field(
        session_file=session_name,
        item_id="1",
        field="dependencies",
        value="Blocks the downstream cutover step",
        base_dir=base_dir,
    )
    assert result.startswith("ERROR: "), result
    assert_names_item_and_field(result, "1", "dependencies")


# ---------------------------------------------------------------------------
# Layer 2 (defence in depth) — the arithmetic itself never sees a bad value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", SCORE_COMPONENTS)
def test_recalc_priority_raises_valueerror_not_typeerror(field):
    """Whatever route a bad value takes, the arithmetic must not TypeError."""
    item = {"id": "example", field: "not a number"}
    with pytest.raises(ValueError) as exc:
        _recalc_priority(item)
    assert_names_item_and_field(str(exc.value), "example", field)


def test_recalc_priority_tolerates_out_of_range_legacy_values():
    """Range is enforced on new input only — old files must still load.

    Nothing ever bounded these values on disk, so applying the range check to
    the normalisation path would make a previously-readable session file
    unloadable.  Type is still enforced; the range is not.
    """
    item = {"id": "legacy", "urgency": 42, "importance": 3,
            "effort": 3, "dependencies": 1}
    assert _recalc_priority(item) == 42 + 3 + (6 - 3) + 1


def test_session_with_out_of_range_scores_still_loads(sessions_dir):
    """End-to-end version of the above, through the real load path."""
    sf = sessions_dir / "session_20260314_150000.json"
    sf.write_text(json.dumps({
        "session_file": sf.name,
        "created": "2026-03-14T15:00:00",
        "title": "Legacy",
        "description": "",
        "status": "active",
        "items": [{"id": 1, "title": "Old", "urgency": 42,
                   "importance": 3, "effort": 3, "dependencies": 1}],
    }))
    item = get_item(sf, 1)
    assert item is not None
    assert item["priority_score"] == 42 + 3 + (6 - 3) + 1
