# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Nothing from outside should surface as a raw interpreter error.

A session file is hand-editable and synced between machines; an
`index.json` row is not something this code wrote; and `blocker` is
whatever `oboe_update_field` last set it to. Each of those reached code
that assumed a shape, and the result was a `TypeError` or
`AttributeError` with no indication of which file or field was wrong —
one of them leaving a parent session permanently paused."""

import json
from pathlib import Path

import pytest

from oboe_mcp.cli import main
from oboe_mcp.server import oboe_create, oboe_list_items
from oboe_mcp.session import (
    _is_valid_index,
    complete_child_session,
    create_child_session,
    create_session,
    get_item,
    list_items,
    list_sessions,
    load_session,
    mark_complete,
    merge_items,
    update_field,
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
# 2. complete_child_session must not wedge the parent
# ---------------------------------------------------------------------------

@pytest.fixture(name="paused_parent")
def fixture_paused_parent(sessions_dir):
    parent = sessions_dir / "session_20260411_120000.json"
    child = sessions_dir / "session_20260411_130000.json"
    create_session(
        parent, [{"id": 1, "title": "P"}], title="T", description="D"
    )
    create_child_session(
        parent, child, [{"id": 1, "title": "C"}],
        title="child", description="d", parent_item_id=1,
    )
    mark_complete(child, 1, "done")
    return parent, child


def test_child_completion_survives_a_non_dict_blocker(paused_parent):
    """oboe_update_field can set `blocker` to a string; `.get` then blew up."""
    parent, child = paused_parent
    update_field(parent, 1, "blocker", "just some text")

    complete_child_session(child, "done")

    session = load_session(parent)
    assert session["active_child_session"] is None
    assert session["status"] != "paused"


def test_child_completion_still_unblocks_a_well_formed_blocker(paused_parent):
    parent, child = paused_parent

    complete_child_session(child, "resolved upstream")

    item = get_item(parent, 1)
    assert item is not None
    assert item["status"] == "pending"
    assert item["blocker"] is None
    assert item["child_session_resolution"] == "resolved upstream"


# ---------------------------------------------------------------------------
# 5 & 6. A structurally-valid index carrying unusable rows
# ---------------------------------------------------------------------------

def _corrupt_rows(sessions_dir) -> None:
    (sessions_dir / "index.json").write_text(
        json.dumps({"format_version": 1, "sessions": ["oops", None, 42]})
    )


def test_is_valid_index_rejects_non_dict_rows():
    bad_row = {"format_version": 1, "sessions": ["oops"]}
    assert _is_valid_index(bad_row) is False
    assert _is_valid_index({"format_version": 1, "sessions": [{}]}) is False
    assert _is_valid_index(
        {"format_version": 1, "sessions": [{"file": 7}]}
    ) is False
    assert _is_valid_index(
        {"format_version": 1, "sessions": [{"file": "session_x.json"}]}
    ) is True


def test_merge_survives_an_index_with_unusable_rows(
    session_file, sessions_dir
):
    """_upsert_index did `row["file"]` and raised TypeError after the write."""
    _corrupt_rows(sessions_dir)

    merge_items(session_file, [{"title": "Second"}])

    index = json.loads((sessions_dir / "index.json").read_text())
    assert _is_valid_index(index)
    assert [r["file"] for r in index["sessions"]] == [session_file.name]


def test_list_sessions_repairs_an_index_with_unusable_rows(
    session_file, sessions_dir
):
    _corrupt_rows(sessions_dir)

    rows = list_sessions(sessions_dir, status_filter="active")

    assert [r["file"] for r in rows] == [session_file.name]


def test_cli_sessions_survives_an_index_with_unusable_rows(
    base_dir, session_file, sessions_dir
):
    _corrupt_rows(sessions_dir)
    out, _ = _run("--base-dir", str(base_dir), "sessions")
    assert session_file.name in out


# ---------------------------------------------------------------------------
# 9. A malformed session file reads as malformed, not as an interpreter error
# ---------------------------------------------------------------------------

MALFORMED = {
    "items_not_a_list": ({"items": "oops"}, "'items' must be a list"),
    "items_is_a_dict": ({"items": {"a": 1}}, "'items' must be a list"),
    "item_is_a_string": ({"items": ["oops"]}, "item #1 must be an object"),
    "item_is_null": ({"items": [None]}, "item #1 must be an object"),
    "second_item_bad": (
        {"items": [{"title": "ok"}, 7]}, "item #2 must be an object",
    ),
    "children_not_a_list": (
        {"items": [], "child_session_files": "nope"},
        "'child_session_files' must be a list",
    ),
}


def _write_doc(sessions_dir, body) -> Path:
    sf = sessions_dir / "session_20260411_120000.json"
    if body is None:
        sf.write_text(json.dumps([1, 2, 3]))
    else:
        sf.write_text(json.dumps({
            "session_file": sf.name, "title": "t", "description": "",
            "status": "active", "created": "2026-04-11", **body,
        }))
    return sf


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_session_names_the_file_and_the_problem(sessions_dir, case):
    body, expected = MALFORMED[case]
    sf = _write_doc(sessions_dir, body)

    with pytest.raises(ValueError) as exc:
        list_items(sf)

    message = str(exc.value)
    assert sf.name in message, message
    assert expected in message, message


@pytest.mark.parametrize(
    "items, expected",
    [
        ("oops", "'items' must be a list"),
        ({"a": 1}, "'items' must be a list"),
        (["oops"], "item #1 must be an object"),
        ([None], "item #1 must be an object"),
        ([{"title": "ok"}, 7], "item #2 must be an object"),
    ],
)
def test_a_malformed_items_argument_says_which_item(
    sessions_dir, items, expected
):
    """The same check as for a file on disk, on the way in."""
    sf = sessions_dir / "session_20260411_150000.json"
    with pytest.raises(ValueError, match=expected):
        create_session(sf, items, title="T", description="D")
    assert not sf.exists()


@pytest.mark.parametrize(
    "items, expected",
    [
        ("oops", "'items' must be a list"),
        ([None], "item #1 must be an object"),
    ],
)
def test_oboe_create_rejects_a_malformed_items_argument(
    base_dir, items, expected
):
    result = oboe_create(
        base_dir=str(base_dir), title="T", description="D", items=items,
        session_file="session_20260411_151000.json",
    )
    assert result.startswith("ERROR: "), result
    assert expected in result
    assert "internal error" not in result


def test_malformed_top_level_document(sessions_dir):
    sf = _write_doc(sessions_dir, None)
    with pytest.raises(ValueError, match="expected a JSON object, got list"):
        list_items(sf)


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_session_surfaces_as_a_tool_error(
    base_dir, sessions_dir, case
):
    body, expected = MALFORMED[case]
    sf = _write_doc(sessions_dir, body)

    from oboe_mcp.server import oboe_list_items

    result = oboe_list_items(session_file=sf.name, base_dir=str(base_dir))

    assert result.startswith("ERROR: Malformed session file"), result
    assert expected in result
    assert "internal error" not in result, (
        "a malformed file on disk is ordinary input, not an internal defect"
    )


@pytest.mark.parametrize("command", [["status"], ["list"], ["show", "1"]])
def test_cli_reports_a_malformed_session_without_a_traceback(
    base_dir, sessions_dir, command
):
    """main() caught only FileNotFoundError and LockError."""
    sf = _write_doc(sessions_dir, {"items": "oops"})
    _, err = _run(
        "--base-dir", str(base_dir), "--session", sf.name, *command,
        expect_rc=1,
    )
    assert "❌" in err
    assert "Malformed session file" in err
    assert "Traceback" not in err


def test_a_malformed_session_does_not_break_listing_the_others(
    base_dir, sessions_dir
):
    """One bad file must not hide every good one from `sessions`."""
    good = sessions_dir / "session_20260411_130000.json"
    create_session(good, [{"id": 1, "title": "Fine"}], title="Good",
                   description="D")
    _write_doc(sessions_dir, {"items": "oops"})
    (sessions_dir / "index.json").unlink()

    rows = {r["file"]: r["status"] for r in list_sessions(sessions_dir)}

    assert rows[good.name] == "active"
    assert rows["session_20260411_120000.json"] == "unreadable"


# ---------------------------------------------------------------------------
# 8. Nothing reaches the client as a raw interpreter error
# ---------------------------------------------------------------------------

def test_tool_boundary_labels_an_unexpected_exception(monkeypatch, base_dir):
    """A defect must arrive as a labelled error, not a raw traceback."""
    import oboe_mcp.server as server_module

    def boom(*_args, **_kwargs):
        raise AttributeError("'str' object has no attribute 'get'")

    monkeypatch.setattr(server_module, "list_sessions", boom)
    result = server_module.oboe_list_sessions(base_dir=str(base_dir))

    assert result.startswith("ERROR: internal error in oboe_list_sessions")
    assert "AttributeError" in result


def test_tool_boundary_preserves_the_published_schema():
    """The wrapper must not flatten the signature MCP clients rely on."""
    import asyncio

    from oboe_mcp.server import mcp

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    schema = tools["oboe_create"].input_schema["properties"]
    assert set(schema) >= {
        "base_dir", "title", "description", "items", "session_file",
    }
    assert "0-5" in schema["items"]["description"]
    assert tools["oboe_create"].description.startswith(
        "Create a new OBO session file"
    )
