# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Item ids must be unique and addressable.

`create_session` accepted duplicates where `merge_items` rejected them,
and `update_field` could rewrite an id into a collision. A shadowed item
is unreachable — every lookup resolves to the first — so it can never be
completed and the session can never finish."""

import json

import pytest

from oboe_mcp.cli import main
from oboe_mcp.server import (
    oboe_create,
    oboe_merge_items,
    oboe_next,
    oboe_update_field,
)
from oboe_mcp.session import (
    create_session,
    get_item,
    list_items,
    merge_items,
    update_field,
    validate_item_id,
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
# 3 & 4. Item ids: duplicates, types, and rewrites
# ---------------------------------------------------------------------------

def test_create_rejects_duplicate_ids(sessions_dir):
    """merge_items rejected these; create_session silently shadowed them."""
    sf = sessions_dir / "session_20260411_140000.json"
    with pytest.raises(ValueError, match="Duplicate item id"):
        create_session(
            sf,
            [{"id": "x", "title": "First"}, {"id": "x", "title": "Second"}],
            title="T", description="D",
        )
    assert not sf.exists()


def test_oboe_create_rejects_duplicate_ids(base_dir):
    result = oboe_create(
        base_dir=str(base_dir), title="T", description="D",
        items=[{"id": 1, "title": "A"}, {"id": 1, "title": "B"}],
        session_file="session_20260411_140000.json",
    )
    assert result.startswith("ERROR: "), result
    assert "Duplicate item id" in result


def test_auto_ids_do_not_collide_with_a_later_explicit_id(sessions_dir):
    """{} then {"id": 1} used to both become 1, shadowing the second."""
    sf = sessions_dir / "session_20260411_141000.json"
    create_session(
        sf,
        [{"title": "Auto"}, {"id": 1, "title": "Explicit"}],
        title="T", description="D",
    )
    ids = sorted(str(i["id"]) for i in list_items(sf))
    assert len(set(ids)) == 2, ids
    titles = {str(i["id"]): i["title"] for i in list_items(sf)}
    assert titles["1"] == "Explicit"


def test_merge_still_rejects_a_duplicate_of_an_existing_id(session_file):
    with pytest.raises(ValueError, match="Duplicate item id"):
        merge_items(session_file, [{"id": 1, "title": "Clash"}])


def test_merge_rejects_a_duplicate_within_its_own_batch(session_file):
    with pytest.raises(ValueError, match="Duplicate item id"):
        merge_items(
            session_file,
            [{"id": "new", "title": "A"}, {"id": "new", "title": "B"}],
        )


def test_merge_appends_beyond_the_highest_existing_id(session_file):
    merge_items(session_file, [{"title": "Second"}])
    assert sorted(i["id"] for i in list_items(session_file)) == [1, 2]


def test_a_rejected_merge_appends_nothing(session_file):
    before = session_file.read_bytes()
    with pytest.raises(ValueError):
        merge_items(
            session_file,
            [{"title": "Fine"}, {"id": 1, "title": "Clash"}],
        )
    assert session_file.read_bytes() == before


@pytest.mark.parametrize("bad", [None, True, False, [], {}, 1.5, "  "])
def test_create_rejects_a_bad_id_type(sessions_dir, bad):
    sf = sessions_dir / "session_20260411_142000.json"
    with pytest.raises(ValueError, match="id"):
        create_session(sf, [{"id": bad, "title": "T"}], title="T",
                       description="D")
    assert not sf.exists()


def test_validate_item_id_accepts_strings_and_integers():
    assert validate_item_id(7) == 7
    assert validate_item_id("phase-1") == "phase-1"


def test_oboe_merge_items_rejects_a_null_id(base_dir, session_file):
    result = oboe_merge_items(
        session_file=session_file.name, base_dir=str(base_dir),
        items=[{"id": None, "title": "T"}],
    )
    assert result.startswith("ERROR: "), result
    assert "id" in result


def test_update_field_refuses_to_change_id(session_file):
    merge_items(session_file, [{"id": 2, "title": "B"}])
    with pytest.raises(ValueError, match="'id' cannot be changed"):
        update_field(session_file, 1, "id", 2)
    assert sorted(i["id"] for i in list_items(session_file)) == [1, 2]


def test_update_field_rejects_an_unknown_field(session_file):
    with pytest.raises(ValueError, match="Unknown item field"):
        update_field(session_file, 1, "totally_made_up", "x")
    item = get_item(session_file, 1)
    assert item is not None
    assert "totally_made_up" not in item


def test_oboe_update_field_rejects_an_unknown_field(base_dir, session_file):
    result = oboe_update_field(
        session_file=session_file.name, item_id="1",
        field="totally_made_up", value="x", base_dir=str(base_dir),
    )
    assert result.startswith("ERROR: "), result
    assert "Unknown item field" in result


@pytest.mark.parametrize(
    "field", ["title", "category", "description", "status", "resolution",
              "urgency", "approval_note", "priority_score"],
)
def test_documented_fields_are_still_updatable(session_file, field):
    values = {"status": "in_progress", "urgency": "4", "priority_score": "9"}
    update_field(session_file, 1, field, values.get(field, "text"))


def test_oboe_next_marks_the_item_it_returned(base_dir, sessions_dir):
    """With duplicate ids this marked a different item than it handed back."""
    sf = sessions_dir / "session_20260411_143000.json"
    create_session(
        sf,
        [{"id": 1, "title": "A", "urgency": 5},
         {"id": 2, "title": "B", "urgency": 1}],
        title="T", description="D",
    )
    result = oboe_next(
        session_file=sf.name, base_dir=str(base_dir), mark_in_progress=True
    )
    returned = json.loads(result)
    in_progress = [
        i["id"] for i in list_items(sf) if i["status"] == "in_progress"
    ]
    assert in_progress == [returned["id"]]


