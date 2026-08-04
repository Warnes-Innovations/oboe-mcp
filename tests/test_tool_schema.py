# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""Tests for the published MCP tool schemas (issue #20, layer 2).

Layer 1 stops a bad ``dependencies`` from crashing the server. Layer 2 is what
stops the caller from sending one: the tool schema and description have to say
that the four priority factors are numbers. These tests assert the contract is
actually *published*, not merely intended — a docstring edit that never
reaches the wire is exactly the failure mode this layer exists to prevent.
"""

import asyncio

import pytest

from oboe_mcp.server import mcp

SCORE_COMPONENTS = ("urgency", "importance", "effort", "dependencies")
ITEM_TOOLS = ("oboe_create", "oboe_merge_items", "oboe_create_child_session")


@pytest.fixture(scope="module", name="tools")
def fixture_tools():
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


def _items_schema(tool) -> dict:
    """Return the schema describing one element of the ``items`` array."""
    param = tool.input_schema["properties"]["items"]
    if "items" in param:
        return param["items"]
    for branch in param.get("anyOf", []):
        if branch.get("type") == "array":
            return branch["items"]
    raise AssertionError(f"no array schema for items on {tool.name}")


@pytest.mark.parametrize("tool_name", ITEM_TOOLS)
@pytest.mark.parametrize("field", SCORE_COMPONENTS)
def test_score_fields_published_as_bounded_numbers(tools, tool_name, field):
    prop = _items_schema(tools[tool_name])["properties"][field]
    assert prop["type"] == "number"
    assert prop["minimum"] == 0
    assert prop["maximum"] == 5
    assert "0-5" in prop["description"]


@pytest.mark.parametrize("tool_name", ITEM_TOOLS)
def test_dependencies_description_disclaims_the_obvious_misreading(
    tools, tool_name
):
    """The field name invites 'what this item depends on'. Say it is not."""
    desc = _items_schema(tools[tool_name])["properties"]["dependencies"]
    text = desc["description"].lower()
    assert "not a description" in text
    assert "pressure" in text


@pytest.mark.parametrize("tool_name", ITEM_TOOLS)
def test_items_parameter_description_states_the_numeric_contract(
    tools, tool_name
):
    param = tools[tool_name].input_schema["properties"]["items"]
    assert "0-5" in param["description"]
    assert "dependencies" in param["description"]


@pytest.mark.parametrize("tool_name", ITEM_TOOLS)
def test_item_schema_still_allows_unlisted_fields(tools, tool_name):
    """Callers pass fields we do not enumerate; do not make them invalid."""
    assert _items_schema(tools[tool_name])["additionalProperties"] is True


def test_oboe_create_description_states_the_numeric_contract(tools):
    text = tools["oboe_create"].description
    assert "0-5" in text
    for field in SCORE_COMPONENTS:
        assert field in text


def test_oboe_update_field_description_states_the_numeric_contract(tools):
    text = tools["oboe_update_field"].description
    assert "0-5" in text
    assert "dependencies" in text
