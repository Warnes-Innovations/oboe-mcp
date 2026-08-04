# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Regression tests for ordering caller-supplied values of mixed type.

``id`` is documented as "string or integer" and ``category`` is free-form
text, and both come straight from the caller. Sorting either one on its raw
value raises ``TypeError: '<' not supported between instances of 'int' and
'str'`` as soon as one session holds both types.

Both are latent rather than obvious because the failing comparison is a
*secondary* key: item ids are only compared when two items tie on
``priority_score``, so a mixed-id session works right up until a tie appears.
"""

import json

import pytest

from oboe_mcp.cli import main
from oboe_mcp.server import oboe_list_items, oboe_next, oboe_session_status
from oboe_mcp.session import create_session, get_next, list_items

# Both items score 3+3+(6-3)+1 = 10, so the id tie-break is always consulted.
MIXED_ID_ITEMS = [
    {"id": "phase-1", "title": "String id"},
    {"id": 2, "title": "Integer id"},
    {"id": "10", "title": "Numeric string id"},
]


def _run(*args: str, expect_rc: int = 0) -> tuple[str, str]:
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


@pytest.fixture(name="mixed_id_session")
def fixture_mixed_id_session(sessions_dir):
    sf = sessions_dir / "session_20260411_120000.json"
    create_session(sf, MIXED_ID_ITEMS, title="Mixed", description="D")
    return sf


# ---------------------------------------------------------------------------
# Item ids: string and integer in one session
# ---------------------------------------------------------------------------

def test_list_items_orders_mixed_ids(mixed_id_session):
    ids = [i["id"] for i in list_items(mixed_id_session)]
    # All three tie on score, so ordering is purely the id tie-break:
    # numeric ids ascending first ("10" counts as 10), then text.
    assert ids == [2, "10", "phase-1"]


def test_get_next_picks_lowest_id_among_mixed(mixed_id_session):
    item = get_next(mixed_id_session)
    assert item is not None
    assert item["id"] == 2


def test_oboe_list_items_survives_mixed_ids(base_dir, mixed_id_session):
    result = oboe_list_items(
        session_file=mixed_id_session.name, base_dir=str(base_dir)
    )
    assert not result.startswith("ERROR: "), result
    assert [i["id"] for i in json.loads(result)["items"]] == [
        2, "10", "phase-1",
    ]


def test_oboe_next_survives_mixed_ids(base_dir, mixed_id_session):
    result = oboe_next(
        session_file=mixed_id_session.name, base_dir=str(base_dir)
    )
    assert not result.startswith("ERROR: "), result
    # oboe_next returns the item dict itself, with progress spliced in.
    assert json.loads(result)["id"] == 2


def test_cli_list_and_next_survive_mixed_ids(base_dir, mixed_id_session):
    out, _ = _run(
        "--base-dir", str(base_dir), "--session", mixed_id_session.name,
        "list",
    )
    assert "phase-1" in out
    out, _ = _run(
        "--base-dir", str(base_dir), "--session", mixed_id_session.name,
        "next",
    )
    assert "NEXT ITEM (ID: 2)" in out


def test_id_ordering_is_still_numeric_for_all_integer_ids(sessions_dir):
    """The tie-break must not become lexicographic: 2 sorts before 10."""
    sf = sessions_dir / "session_20260411_121000.json"
    create_session(
        sf,
        [{"id": 10, "title": "Ten"}, {"id": 2, "title": "Two"}],
        title="T", description="D",
    )
    assert [i["id"] for i in list_items(sf)] == [2, 10]


def test_priority_still_outranks_id(sessions_dir):
    """The id is a tie-break only; a higher score must still win."""
    sf = sessions_dir / "session_20260411_122000.json"
    create_session(
        sf,
        [
            {"id": 1, "title": "Low", "urgency": 0},
            {"id": "zzz", "title": "High", "urgency": 5},
        ],
        title="T", description="D",
    )
    assert [i["id"] for i in list_items(sf)] == ["zzz", 1]


# ---------------------------------------------------------------------------
# Categories: string and non-string in one session
# ---------------------------------------------------------------------------

def test_cli_status_survives_mixed_category_types(base_dir, sessions_dir):
    """`category` is untyped: one session can hold 5 and 'General'."""
    sf = sessions_dir / "session_20260411_130000.json"
    create_session(
        sf,
        [
            {"title": "A", "category": 5},
            {"title": "B", "category": "General"},
        ],
        title="T", description="D",
    )
    out, _ = _run(
        "--base-dir", str(base_dir), "--session", sf.name, "status",
    )
    assert "By Category" in out
    assert "General" in out
    assert "5" in out


def test_oboe_session_status_survives_mixed_category_types(
    base_dir, sessions_dir
):
    sf = sessions_dir / "session_20260411_131000.json"
    create_session(
        sf,
        [
            {"title": "A", "category": 5},
            {"title": "B", "category": "General"},
        ],
        title="T", description="D",
    )
    result = oboe_session_status(
        session_file=sf.name, base_dir=str(base_dir)
    )
    assert not result.startswith("ERROR: "), result
    assert json.loads(result)["total"] == 2
