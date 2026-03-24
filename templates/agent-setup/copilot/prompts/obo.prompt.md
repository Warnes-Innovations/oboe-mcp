---
description: "Process multiple items sequentially with priority scoring, resume handling, and persistent OBO session state"
name: "OBO Review Session"
argument-hint: "Optional context or item source such as a finding list, task list, or requirements"
agent: "agent"
tools: [obo-mcp/*]
---

Use the `obo-mcp` MCP server to manage a One-By-One review session for the current workspace.

Follow this workflow:

1. Call `obo_list_sessions` for the current workspace before extracting new items.
2. If an incomplete session exists, ask whether to resume, merge, defer, replace, or stop.
3. If creating a new session, extract discrete items from the current context.
4. Assign priority factors for each item using urgency, importance, effort, and dependencies.
5. Call `obo_create` to persist the session.
6. If adding to an existing session, call `obo_merge_items`.
7. Present an executive summary before reviewing individual items. Include scope, item count, highest-impact items, important dependencies, and proposed order.
8. Use `obo_next` to choose the next actionable item.
9. Use `obo_mark_in_progress` when work begins on an item.
10. If an item cannot proceed, call `obo_mark_blocked` and store blocker details instead of losing the stalled state in chat.
11. If a sub-problem needs its own queue, call `obo_create_child_session`, finish the child workflow, then call `obo_complete_child_session` to resume the parent.
12. Treat item state as two axes: lifecycle (`pending`, `in_progress`, `deferred`, `blocked`, `completed`, `skipped`) and approval (`unreviewed`, `approved`, `denied`).
13. Use `obo_set_approval` for approval metadata such as `approval_status`, `approval_mode`, and `approval_note`.
14. Approve Immediate means `obo_set_approval(..., approval_status="approved", approval_mode="immediate")`; Approve Delayed means `obo_set_approval(..., approval_status="approved", approval_mode="delayed")`.
15. After user approval or denial, use `obo_mark_complete` or `obo_mark_skip`.
16. Use `obo_session_status` to report progress after each decision.
17. When no open items remain, call `obo_complete_session`.

Rules:

- Never directly edit `.github/obo_sessions/*.json` or `index.json`.
- Never synthesize session state from manual file writes when an `obo_*` tool exists.
- Prefer OBO for multi-item workflows that need resumable queue state; prefer normal chat for one-off tasks.
- Reorder work intentionally using impact and dependency information instead of chat order.
- Present one item at a time and do not advance until the user explicitly approves, denies, skips, or asks to move on.
- If the MCP surface cannot perform a requested operation, stop and tell the user what is missing.

Input to process: ${input}
