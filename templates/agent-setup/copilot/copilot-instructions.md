<!--
Copyright (C) 2026 Gregory R. Warnes
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of Oboe MCP.
For commercial licensing, contact greg@warnes-innovations.com
-->

# OBO Session Guidelines

Use the OBO MCP tools for all One-By-One review session work in this workspace.

## When To Use OBO

- Use OBO when the user asks to work through items one by one or sequentially.
- Use OBO when multiple findings, tasks, or decisions need explicit user approval one item at a time.
- Use OBO when the work should survive across long conversations, model restarts, or handoff to another agent.
- Use OBO when the work may need to be reordered, blocked, or split into a nested child session.
- Prefer normal chat for small single-step tasks where persistent queue state would add unnecessary overhead.

## Required Workflow

- Never directly create, edit, repair, or reorder files in `.github/obo_sessions/`.
- Use `obo_list_sessions` before starting a new OBO session.
- If an incomplete session exists, ask the user whether to resume, merge, replace, or stop.
- Use `obo_create` to start a new session.
- Use `obo_merge_items` to append new findings to an existing session.
- Use the `one-by-one` skill when available to decide whether the task should become an OBO workflow.
- Start the session with an overview of scope, item count, major dependencies, and proposed order.
- Use `obo_next` to fetch the next actionable item.
- Use `obo_mark_in_progress` when beginning work on an item.
- Use `obo_mark_blocked` when an item cannot proceed and blocker information should be preserved.
- Use `obo_create_child_session` when a sub-problem needs its own nested OBO workflow.
- Use `obo_complete_child_session` to close a child session and resume the parent.
- Use `obo_set_approval` to record approval decisions, timing, and delayed-review transitions.
- Use `obo_mark_complete` or `obo_mark_skip` to resolve an item.
- Use `obo_session_status` or `obo_list_items` instead of reading `index.json` directly.
- Use `obo_complete_session` when all actionable items are resolved.

## Session Conventions

- Session files live in `.github/obo_sessions/`.
- New session filenames must follow `session_YYYYMMDD_HHMMSS.json`.
- Item lifecycle states include `pending`, `in_progress`, `deferred`, `blocked`, `completed`, and `skipped`.
- Item approval states include `unreviewed`, `approved`, and `denied`; approval timing is stored in `approval_mode` as `immediate`, `delayed`, or `null`.
- Parent sessions may be `paused` while a child session is active.
- Treat the MCP server as the source of truth for session state.

## Review Behavior

- For multiple findings, keep the OBO session updated after every user-approved action.
- For a single finding, still use the MCP session flow if the user asks for OBO handling.
- If a needed operation is not available through the MCP tools, tell the user instead of editing session JSON manually.