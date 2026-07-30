<!--
Copyright (C) 2026 Gregory R. Warnes
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of Oboe MCP.
For commercial licensing, contact greg@warnes-innovations.com
-->

# OBO Session Format Specification

**Last Updated:** 2026-03-24 12:12 EDT

**Executive Summary:** This document specifies the on-disk format used by oboe-mcp for OBO session state. It covers the session directory layout, filename rules, session JSON schema, item schema, the lifecycle and approval axes, derived fields, child-session relationships, and the companion index file.

## Contents

- [Paths And Filenames](#paths-and-filenames)
- [Directory Layout](#directory-layout)
- [Session File Schema](#session-file-schema)
- [Item Schema](#item-schema)
- [Status Semantics](#status-semantics)
- [Priority Score](#priority-score)
- [Index File Schema](#index-file-schema)
- [Lifecycle Notes](#lifecycle-notes)
- [Example Session File](#example-session-file)

## Paths And Filenames

- Session root directory: `{base_dir}/.github/oboe_sessions/`
- Session index file: `{base_dir}/.github/oboe_sessions/index.json`
- Session file pattern: `session_YYYYMMDD_HHMMSS.json`
- Session filename validation regex: `^session_\d{8}_\d{6}\.json$`

Path resolution rules:

- Public APIs may accept either an absolute session file path or a bare filename.
- A bare filename is resolved relative to `{base_dir}/.github/oboe_sessions/`.
- New sessions created through `oboe_create` and child sessions created through `oboe_create_child_session` must follow the filename convention above.

## Directory Layout

Typical layout:

```text
{base_dir}/
  .github/
    oboe_sessions/
      index.json
      session_20260323_191200.json
      session_20260323_193000.json
```

Notes:

- `index.json` is a derived summary file used as a fast path for listing sessions.
- `session_*.json` files are the source of truth for per-session state.
- If `index.json` is missing, corrupt, or structurally invalid, oboe-mcp can rebuild it by scanning the session files on disk.

## Session File Schema

Each session file is a JSON object with these top-level fields.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `session_file` | string | yes | The session filename, for example `session_20260323_191200.json`. |
| `created` | string | yes | ISO 8601 timestamp for session creation. |
| `title` | string | yes | Human-readable session title. Defaults to the session stem when omitted at creation time. |
| `description` | string | yes | Free-text description of the session. Defaults to the empty string. |
| `status` | string | yes | Session status: `active`, `paused`, or `completed`. |
| `parent_session_file` | string or null | yes | Parent session filename when this is a child session, otherwise `null`. |
| `parent_item_id` | string, integer, or null | yes | Parent item that spawned this child session, otherwise `null`. |
| `child_session_files` | array of strings | yes | Filenames of child sessions created from this session. |
| `active_child_session` | string or null | yes | The currently active child session filename, if any. |
| `items` | array of objects | yes | Ordered list of session items. |
| `completed_at` | string | conditional | ISO 8601 timestamp set when the session becomes completed. Omitted while the session is `active` or `paused`. |

Additional notes:

- `status` is derived from session state and open items, not treated as an arbitrary free-form field.
- A session becomes `paused` when `active_child_session` is set.
- A session becomes `completed` only when no open items remain.
- A completed child session still retains `parent_session_file` and `parent_item_id` for auditability.

## Item Schema

Each entry in `items` is a JSON object with these fields.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string or integer | yes | Item identifier. If omitted during creation, oboe-mcp assigns a sequential integer starting at 1. |
| `status` | string | yes | Lifecycle status: `pending`, `in_progress`, `deferred`, `blocked`, `completed`, or `skipped`. |
| `title` | string | yes | Short label for the item. Defaults to `Item {id}`. |
| `category` | string | yes | Category label. Defaults to `General`. |
| `description` | string | yes | Free-text detail for the item. Defaults to the empty string. |
| `urgency` | integer | yes | Priority input, default `3`. |
| `importance` | integer | yes | Priority input, default `3`. |
| `effort` | integer | yes | Priority input, default `3`. |
| `dependencies` | integer | yes | Priority input, default `1`. |
| `priority_score` | integer | yes | Derived score computed from the priority inputs. |
| `resolution` | string or null | yes | Completion text set by `oboe_mark_complete`, otherwise `null`. |
| `skip_reason` | string or null | yes | Skip reason set by `oboe_mark_skip`, otherwise `null`. |
| `blocker` | object or null | yes | Structured blocker payload when an item is blocked, otherwise `null`. |
| `blocked_at` | string or null | yes | ISO 8601 timestamp recorded when an item becomes blocked, otherwise `null`. |
| `approval_status` | string | yes | Approval status: `unreviewed`, `approved`, or `denied`. Defaults to `unreviewed`. |
| `approval_mode` | string or null | yes | Approval timing mode: `immediate`, `delayed`, or `null` when no timing has been recorded. |
| `approved_at` | string or null | yes | ISO 8601 timestamp set when approval is recorded, otherwise `null`. |
| `approval_note` | string or null | yes | Optional note explaining the approval decision. |
| `child_session_resolution` | string | conditional | Optional resolution note copied back to the parent item when a child session is completed with a resolution string. |

Normalization defaults:

- New items are normalized at creation or merge time.
- Missing `priority_score` is always recalculated from the score component fields.
- If an item moves out of `blocked`, oboe-mcp clears `blocker` and `blocked_at`.

## Status Semantics

OBO stores state on two axes: lifecycle and approval.

Lifecycle statuses:

- `pending`: actionable work not yet started
- `in_progress`: currently being worked
- `deferred`: approved work that is intentionally parked until the review pass is complete or the user requests deferred work
- `blocked`: cannot proceed; blocker state is preserved in the item
- `completed`: resolved and closed
- `skipped`: intentionally not pursued

Approval statuses:

- `unreviewed`: no explicit user decision is recorded yet
- `approved`: the user approved the item for execution
- `denied`: the user explicitly rejected the item

Approval mode values:

- `immediate`: approved for execution now
- `delayed`: approved for later execution
- `null`: no approval timing decision recorded

Session statuses:

- `active`: session has open work and no active child session
- `paused`: session is waiting on an active child session
- `completed`: no open items remain

Open-item semantics:

- Open item statuses are `pending`, `in_progress`, `deferred`, and `blocked`.
- Actionable item statuses are `pending` and `in_progress`.
- Terminal item statuses are `completed` and `skipped`.
- `deferred` stays open so it remains visible in session status and blocks session completion, but it is not treated as immediately actionable until the primary review queue is exhausted.

## Priority Score

The priority score is recalculated with this formula:

$$
priority\_score = urgency + importance + (6 - effort) + dependencies
$$

Sorting rules used by the session helpers:

- `oboe_next` prefers `in_progress` items first.
- It then falls back to `pending` items.
- If no immediate review items remain, it falls back to `deferred` items.
- Within the same status bucket, higher `priority_score` sorts first.
- For ties, lower `id` sorts first.
- `oboe_list_items` sorts all items by descending `priority_score`, then ascending `id`.

## Index File Schema

`index.json` is a JSON object with this top-level structure:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `format_version` | integer | yes | Current index format version. The current value is `1`. |
| `last_updated` | string | yes | ISO 8601 timestamp for the last index write. |
| `sessions` | array of objects | yes | Summary rows for each session file. |

Each session summary row contains:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `file` | string | yes | Session filename. |
| `title` | string | yes | Session title. |
| `status` | string | yes | Session status or `unreadable` during rebuild fallback. |
| `pending` | integer | yes | Count of pending items. |
| `in_progress` | integer | yes | Count of in-progress items. |
| `deferred` | integer | yes | Count of deferred items. |
| `blocked` | integer | yes | Count of blocked items. |
| `actionable` | integer | yes | Count of actionable items: `pending` plus `in_progress`. |
| `open` | integer | yes | Count of open items: `pending` plus `in_progress` plus `deferred` plus `blocked`. |
| `created` | string | yes | Session creation date truncated to `YYYY-MM-DD`. |
| `parent_session_file` | string or null | yes | Parent session filename when present. |
| `active_child_session` | string or null | yes | Active child session filename when present. |

Index maintenance behavior:

- Mutating session operations update the corresponding `index.json` entry.
- Listing sessions can rebuild the entire index when the stored index is absent or invalid.
- `index.json` should be treated as a managed artifact, not hand-edited application state.

## Lifecycle Notes

The session helpers maintain several cross-field invariants:

- Creating a child session appends the child filename to `child_session_files` on the parent.
- Creating a child session sets `active_child_session` on the parent.
- Creating a child session against a specific parent item marks that parent item `blocked` with a `blocker` payload of type `child_session`.
- Completing a child session clears `active_child_session` on the parent.
- Completing a child session restores the parent item from `blocked` to `pending` when that item was blocked by the child session.
- Completing a child session may also write `child_session_resolution` onto the parent item.
- Recording delayed approval should typically pair `approval_status=approved`, `approval_mode=delayed`, and `status=deferred`.
- Recording a denial should typically pair `approval_status=denied` with a terminal lifecycle state such as `skipped`.
- Completing a session while any open items remain raises an error.

## Example Session File

```json
{
  "session_file": "session_20260323_191200.json",
  "created": "2026-03-23T19:12:00.123456",
  "title": "Toy app review",
  "description": "Five review findings to process one by one.",
  "status": "active",
  "parent_session_file": null,
  "parent_item_id": null,
  "child_session_files": [
    "session_20260323_193000.json"
  ],
  "active_child_session": null,
  "items": [
    {
      "id": 1,
      "status": "completed",
      "title": "Fix password logging",
      "category": "Security",
      "description": "Remove plaintext password logging from the login handler.",
      "urgency": 5,
      "importance": 5,
      "effort": 2,
      "dependencies": 1,
      "resolution": "Removed the log statement and added a regression test.",
      "skip_reason": null,
      "blocker": null,
      "blocked_at": null,
      "approval_status": "approved",
      "approval_mode": "immediate",
      "approved_at": "2026-03-23T19:12:02.000000",
      "approval_note": "Approved for immediate execution during review.",
      "priority_score": 15
    },
    {
      "id": 2,
      "status": "completed",
      "title": "Add missing input validation on the create-task endpoint",
      "category": "API",
      "description": "Validate request payload fields before creating a task.",
      "urgency": 4,
      "importance": 4,
      "effort": 2,
      "dependencies": 1,
      "resolution": "Added request validation and clear 400 responses for invalid input.",
      "skip_reason": null,
      "blocker": null,
      "blocked_at": null,
      "approval_status": "approved",
      "approval_mode": "immediate",
      "approved_at": "2026-03-23T19:14:10.000000",
      "approval_note": null,
      "priority_score": 13
    },
    {
      "id": 3,
      "status": "pending",
      "title": "Add a regression test for duplicate task IDs",
      "category": "Testing",
      "description": "Add coverage that confirms duplicate task IDs are rejected after validation rules are finalized.",
      "urgency": 3,
      "importance": 4,
      "effort": 2,
      "dependencies": 4,
      "resolution": null,
      "skip_reason": null,
      "blocker": null,
      "blocked_at": null,
      "approval_status": "unreviewed",
      "approval_mode": null,
      "approved_at": null,
      "approval_note": null,
      "priority_score": 15
    },
    {
      "id": 4,
      "status": "blocked",
      "title": "Resolve a race condition in the background sync job",
      "category": "Concurrency",
      "description": "Investigate duplicate updates in the sync worker.",
      "urgency": 4,
      "importance": 4,
      "effort": 4,
      "dependencies": 2,
      "resolution": null,
      "skip_reason": null,
      "blocker": {
        "type": "child_session",
        "session_file": "session_20260323_193000.json",
        "title": "Race condition investigation",
        "summary": "Parent work is blocked until child session session_20260323_193000.json is completed"
      },
      "blocked_at": "2026-03-23T19:30:00.654321",
      "approval_status": "approved",
      "approval_mode": "delayed",
      "approved_at": "2026-03-23T19:18:55.000000",
      "approval_note": "Approved for execution after dependency work is reviewed.",
      "priority_score": 12
    },
    {
      "id": 5,
      "status": "pending",
      "title": "Improve an ambiguous settings label in the UI",
      "category": "UX",
      "description": "Rename the settings label so users can tell whether it controls sync or notifications.",
      "urgency": 1,
      "importance": 2,
      "effort": 1,
      "dependencies": 1,
      "resolution": null,
      "skip_reason": null,
      "blocker": null,
      "blocked_at": null,
      "approval_status": "unreviewed",
      "approval_mode": null,
      "approved_at": null,
      "approval_note": null,
      "priority_score": 9
    }
  ]
}
```
