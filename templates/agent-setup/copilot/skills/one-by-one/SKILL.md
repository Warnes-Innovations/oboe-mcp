---
name: one-by-one
description: Process multiple items sequentially with priority scoring and focused navigation. Use when the user asks to work through a list of tasks, findings, or decisions one item at a time, or when resumable OBO session state is needed.
---

Process multiple items sequentially with priority scoring, dependency analysis, and persistent session state.

## When to Use

- The user asks to process tasks, findings, or decisions one by one.
- The work contains multiple items that need explicit sequential approval.
- The agent needs resumable state across long conversations or handoffs.
- The task needs durable tracking rather than relying only on chat history.
- The work may need reprioritization, blocker tracking, or nested sub-sessions.

## Session Management

Prefer the `obo-mcp` MCP tools for `.github/obo_sessions/` state.
Do not read or write session JSON directly when the MCP tools can perform the operation.
If `obo-mcp` is unavailable, stop and surface the blocker instead of silently falling back.

## Key Operations

| Operation | How |
|-----------|-----|
| List existing sessions | `obo_list_sessions(base_dir, status_filter?)` |
| Create new session | `obo_create(base_dir, title, description, items=[...])` |
| Merge into session | `obo_merge_items(session_file, items=[...], base_dir?)` |
| Mark item blocked | `obo_mark_blocked(session_file, item_id, blocker, base_dir?)` |
| Mark item complete | `obo_mark_complete(session_file, item_id, resolution, base_dir?)` |
| Skip item | `obo_mark_skip(session_file, item_id, base_dir?, reason?)` |
| Mark item in progress | `obo_mark_in_progress(session_file, item_id, base_dir?)` |
| Create child session | `obo_create_child_session(parent_session_file, title, description, items, base_dir?, parent_item_id?, session_filename?)` |
| Complete child session | `obo_complete_child_session(child_session_file, base_dir?, resolution?)` |
| Update a field | `obo_update_field(session_file, item_id, field, value, base_dir?)` |
| Find next item | `obo_next(session_file, base_dir?)` |
| Session status | `obo_session_status(session_file, base_dir?)` |
| Complete session | `obo_complete_session(session_file, base_dir?)` |

## Priority Score Formula

`priority_score = urgency + importance + (6 - effort) + dependencies`

Defaults when not supplied: urgency=3, importance=3, effort=3, dependencies=1

## Item Status Values

`pending` | `in_progress` | `blocked` | `completed` | `skipped`

## Session Status Values

`active` | `paused` | `completed`

## Workflow Summary

1. Check for incomplete sessions first.
2. Offer resume, merge, replace, or stop when relevant.
3. Extract items and assign priority factors.
4. Persist the session with `obo_create` or `obo_merge_items`.
5. Present an executive summary for the full list, including major dependencies and proposed order.
6. Present one item at a time.
7. Mark items `blocked` when progress cannot continue and store the blocker.
8. Create a child session when a sub-problem needs its own sequential queue.
9. Do not advance until the user explicitly approves, denies, skips, blocks, or asks to continue.

For the full step-by-step conversational workflow, use the packaged `/obo` prompt at `.github/prompts/obo.prompt.md`.