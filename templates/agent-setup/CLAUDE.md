<!--
Copyright (C) 2026 Gregory R. Warnes
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of Oboe MCP.
For commercial licensing, contact greg@warnes-innovations.com
-->

# OBO Session Guidelines

Use the OBO MCP tools for all One-By-One review session work in this repository.

## When To Use OBO

- Use OBO when the user asks to process findings, tasks, or decisions one at a time.
- Use OBO when multiple review findings need explicit sequential approval instead of a flat summary.
- Use OBO when the item list should be resumable and persisted outside the current chat transcript.
- Use OBO when the work may need reordering, blocker tracking, or nested child sessions.
- Prefer normal chat for small single-step tasks that do not need queue state.

## Required Workflow

- Never directly create, edit, repair, or reorder files in `.github/oboe_sessions/`.
- Use `oboe_list_sessions` before starting a new OBO session.
- If an incomplete session exists, use the agent's structured question UI/tool when available to ask whether to resume, merge, replace, or stop.
- Use `oboe_create` to start a new session. `items` is optional; if items are not yet known, omit them and add them later with `oboe_merge_items`.
- Use `oboe_merge_items` to append new findings to an existing session.
- Start the session with an overview of scope, major dependencies, and proposed order.
- Use `oboe_next` to fetch the next actionable item.
- Use `oboe_mark_in_progress` when beginning work on an item.
- Use `oboe_mark_blocked` when an item cannot proceed and the blocker should be stored.
- Use `oboe_create_child_session` when a nested sub-session is needed.
- Use `oboe_complete_child_session` to finish the child and resume the parent.
- Use `oboe_set_approval` to record approval decisions, timing, and delayed-review transitions.
- Use `oboe_mark_complete` or `oboe_mark_skip` to resolve an item.
- Use `oboe_session_status` or `oboe_list_items` instead of reading `index.json` directly.
- Use `oboe_complete_session` when all actionable items are resolved.
- Use the agent's structured question UI/tool for predefined OBO choices such as resume, merge, replace, approval, navigation, stop, restore, and reorder instead of plain-text numbered menus.
- Only fall back to plain text when no structured question tool exists, the tool is failing, or the response truly must be open-ended; state that reason explicitly before falling back.

## Session Conventions

- Session files live in `.github/oboe_sessions/`.
- New session filenames must follow `session_YYYYMMDD_HHMMSS.json`.
- Item lifecycle states include `pending`, `in_progress`, `deferred`, `blocked`, `completed`, and `skipped`.
- Item approval states include `unreviewed`, `approved`, and `denied`; approval timing is stored in `approval_mode` as `immediate`, `delayed`, or `null`.
- Parent sessions may be `paused` while a child session is active.
- Treat the MCP server as the source of truth for session state.

## Review Behavior

- For multiple findings, keep the OBO session updated after every user-approved action.
- For a single finding, still use the MCP session flow if the user asks for OBO handling.
- If a needed operation is not available through the MCP tools, tell the user instead of editing session JSON manually.

## Release Workflow

- Treat testing, tagging, releasing, and publishing as a staged workflow: inspect repo state, run tests, complete release-prep edits, validate packaging, then handle remote release steps.
- Prefer the verified release test command `.venv/bin/python -m pytest tests/test_session.py tests/test_server.py` unless the user explicitly requests a different scope.
- Keep release edits minimal and targeted. Do not revert unrelated dirty-worktree files unless the user explicitly asks.
- Before any irreversible action, pause for confirmation even if the user's initial request already said to publish.
- The required confirmation boundary includes each of these actions: `git push`, tag creation, GitHub release creation, and PyPI publication.
- When asking for confirmation, summarize the exact action, the version, and the branch or tag involved.
- After a live publish, verify the result end to end: release workflow status, PyPI visibility, and at least one package resolution or install check.
- If clarification, triage, or blocker handling is needed during release work, prefer creating or resuming an OBO session instead of handling it as an unstructured side conversation.
