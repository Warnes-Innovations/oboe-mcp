# obo-mcp

MCP server for managing One-By-One (OBO) review sessions.

Provides 15 tools for creating, navigating, and resolving items in priority-scored session files, including blocked-item handling and nested child sessions, so `/obo` workflows can use MCP operations instead of raw JSON edits.

## Tools

| Tool | Description |
| ---- | ----------- |
| `obo_create` | Create session file + update index.json atomically |
| `obo_list_sessions` | List sessions from index.json |
| `obo_session_status` | Summary stats for a session |
| `obo_next` | Next item: in_progress first, then highest-priority pending |
| `obo_list_items` | All items sorted by priority_score desc |
| `obo_get_item` | Full detail for one item |
| `obo_mark_blocked` | Mark an item blocked and store blocker information |
| `obo_mark_complete` | Mark item completed with resolution text |
| `obo_mark_in_progress` | Mark item in progress |
| `obo_mark_skip` | Mark item skipped |
| `obo_complete_session` | Mark a session completed when no actionable items remain |
| `obo_create_child_session` | Create a child session, pause the parent, and step into the child |
| `obo_complete_child_session` | Complete a child session and resume the parent |
| `obo_merge_items` | Append new items to an existing session and reactivate it |
| `obo_update_field` | Update any field; auto-recalculates priority_score |

## Installation

**Phase A (local dev):**

```json
"obo-mcp": {
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "/Users/warnes/src/obo-mcp", "obo-mcp"]
}
```

**Phase C (GitHub URL):**

```json
"obo-mcp": {
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "git+https://github.com/warnes-innovations/obo-mcp", "obo-mcp"]
}
```

## Why OBO Sessions

One-by-One sessions are not just saved chat notes. They are a workflow model for handling multi-item work as a durable, ordered interaction session.

Compared with plain chat or an agent's built-in follow-up questions, OBO adds capabilities that those lighter interaction modes do not usually provide:

- an overview-first workflow, where the agent can begin with the scope, item count, major categories, and proposed execution order
- explicit reprioritization based on urgency, importance, effort, and dependency pressure instead of whatever order happened to appear in chat
- durable item states through `pending`, `in_progress`, `blocked`, `completed`, and `skipped`
- stored blocker metadata so blocked work is still visible and explainable instead of silently disappearing from the active queue
- nested child sessions that pause a parent session, handle a sub-problem, then resume the parent session cleanly
- first-class session lifecycle management: list, create, inspect, merge, pause, resume, and close sessions as named workflow objects
- deterministic recovery after model restarts, editor reloads, or agent handoff
- a machine-readable audit trail in session files instead of relying on conversational memory

This matters most when the work spans many findings, requires explicit user approvals, depends on intermediate sub-investigations, or must survive across several agent turns. Chat is good at conversation. A structured question tool is good at getting a clean answer in the current turn. OBO is for durable workflow orchestration.

Use OBO when you need controlled sequential handling, durable queue state, or nested sub-work. Use plain chat when the task is small enough that a full workflow object would add more overhead than value.

## Interaction Modes

The three common interaction patterns are plain chat, a structured question tool, and a full OBO session. They solve different problems.

| Standard chat | askQuestions style interaction | One-by-One session |
| --- | --- | --- |
| Best for small, fast back-and-forth tasks where the state can stay in the conversation. | Best when the agent needs the user to choose from a short set of options in the current turn. | Best when work involves multiple findings or decisions that must be tracked, resumed, reordered, blocked, nested, or approved one item at a time. |
| State is mostly conversational and can become hard to recover after a long session. | State is still mostly conversational; the question tool improves input quality but does not provide durable workflow state by itself. | State is persisted to `.github/obo_sessions/`, so another session or another agent can resume cleanly with explicit item and session status. |
| Good example: "rename this function" or "explain this error". | Good example: "resume, merge, replace, or stop?" | Good example: "review these 12 findings one by one and wait for approval on each". |
| Main benefit: lowest friction. | Main benefit: clearer user decisions and fewer ambiguous replies. | Main benefit: durable queue management, explicit blockers, nested sub-sessions, and deterministic recovery across many items. |

Example progression:

- Standard chat: an agent lists several findings in prose and the conversation itself becomes the only record of what was handled.
- askQuestions: the agent can ask for a clean menu choice, but still has no persistent item queue unless it stores one elsewhere.
- OBO session: the agent starts with an overview, stores the full item list, orders it intentionally, records approvals, skips, and blockers, and can resume later without reconstructing the session from chat history.

### Toy Example: Five Review Items

Suppose an agent reviews a small toy to-do app and finds five items:

1. Fix password logging in the login handler.
2. Add missing input validation on the create-task endpoint.
3. Resolve a race condition in the background sync job.
4. Improve an ambiguous settings label in the UI.
5. Add a regression test for duplicate task IDs.

| Standard chat | askQuestions style interaction | One-by-One session |
| --- | --- | --- |
| The agent posts all 5 findings in one message and asks what to do next. | The agent can ask a focused question such as "Which of these five items should we do first?" or "Resume, merge, replace, or stop?" | The agent creates a session containing all 5 items, starts with an overview, assigns priority factors, and presents them in order. |
| The user might reply "do 1, 2, and 5 first," but the conversation is now the only source of truth. | The user gets cleaner choices, but the agent still has to track the full 5-item list elsewhere. | Item 1 can be marked `in_progress`, completed, blocked with stored blocker details, or skipped, then the agent can continue with state preserved. |
| If item 3 turns out to require a separate dependency investigation, that detour has to be tracked informally in chat. | The tool can help choose the next step, but it does not create a nested workflow object by itself. | If item 3 needs a sub-investigation, the agent can open a child session, pause the parent, complete the child, then resume the parent. |
| If the session is interrupted, another agent has to reconstruct which of the 5 items were already accepted or finished. | If the agent restarts, the menu interaction is gone unless some other persistence layer was added. | If the session is interrupted, another agent can resume the saved OBO session and continue from the next unresolved item. |
| Good when the user only wants a quick overview of the 5 findings. | Good when the next step is a single short decision about the 5 findings. | Good when the user wants the 5 findings handled sequentially with explicit approvals and durable progress. |

## Agent Setup

Installing the MCP server gives agents access to the `obo_*` tools, but it does not by itself guarantee that agents will use them correctly. To make agent behavior reliable, distribute both the MCP server configuration and shared agent instructions.

This repository includes reusable templates under `templates/agent-setup/`:

- `templates/agent-setup/copilot/copilot-instructions.md`
- `templates/agent-setup/copilot/skills/one-by-one/SKILL.md`
- `templates/agent-setup/copilot/prompts/obo.prompt.md`
- `templates/agent-setup/AGENTS.md`
- `templates/agent-setup/CLAUDE.md`

### GitHub Copilot

For Copilot, install the MCP server and add explicit workspace instructions so the agent prefers `obo_*` tools over direct JSON edits.

1. Register `obo-mcp` in the MCP client used by Copilot.
2. If the target repository already has `.github/copilot-instructions.md`, merge
  the OBO rules from `templates/agent-setup/copilot/copilot-instructions.md`
  into the existing file instead of overwriting it.
3. If the target repository does not already have `.github/copilot-instructions.md`, create it from
  `templates/agent-setup/copilot/copilot-instructions.md`.
4. If the target repository already has `.github/skills/one-by-one/SKILL.md`, merge the packaged OBO skill guidance from
  `templates/agent-setup/copilot/skills/one-by-one/SKILL.md`. Otherwise create
  `.github/skills/one-by-one/SKILL.md` from the packaged version.
5. If you want a reusable `/obo` prompt and `.github/prompts/obo.prompt.md` already exists, merge the OBO workflow into that prompt or create a separate
  prompt file. Otherwise create it from
  `templates/agent-setup/copilot/prompts/obo.prompt.md`.
6. Adjust the wording if the target repository has project-specific review rules or existing instruction files with overlapping guidance.

The `copilot/` folder in this repository is only a visible packaging location. When consumers install these templates in their own repositories, the files should still live under `.github/` so Copilot can discover them.

The Copilot instruction template tells agents to:

- avoid direct edits to `.github/obo_sessions/*.json`
- use OBO when the user asks for one-by-one handling, when multiple findings need explicit sequential approval, or when resumable queue state is needed
- use `obo_list_sessions`, `obo_create`, `obo_merge_items`, `obo_next`,
  `obo_mark_in_progress`, `obo_mark_blocked`, `obo_mark_complete`,
  `obo_mark_skip`, `obo_create_child_session`,
  `obo_complete_child_session`, `obo_session_status`, and
  `obo_complete_session`
- ask the user whether to resume, merge, replace, or stop when an active session already exists

The packaged skill provides the trigger logic for when OBO should be used, and the prompt template provides an on-demand `/obo` workflow that walks an agent through the full sequential session lifecycle using the MCP server.

### Codex

Codex reads shared project instructions from `AGENTS.md` and MCP server configuration from `~/.codex/config.toml`.

Add `obo-mcp` to the `~/.codex/config.toml` file:

```toml
[mcp_servers.obo-mcp]
command = "uvx"
args = ["--from", "git+https://github.com/warnes-innovations/obo-mcp", "obo-mcp"]
```

Then copy `templates/agent-setup/AGENTS.md` into the target repository as `AGENTS.md`. If the repository already has an `AGENTS.md`, merge the OBO rules into the existing file instead of replacing it. Keep the trigger guidance that explains when agents should switch from normal chat to OBO handling.

### Claude Code

Claude Code can register local stdio MCP servers with `claude mcp add` and uses `CLAUDE.md` or `.claude/CLAUDE.md` for persistent project instructions.

Add `obo-mcp` to Claude Code:

```bash
claude mcp add --transport stdio --scope project obo-mcp -- \
  uvx --from git+https://github.com/warnes-innovations/obo-mcp obo-mcp
```

Then copy `templates/agent-setup/CLAUDE.md` into the target repository as `CLAUDE.md` or `.claude/CLAUDE.md`. If the repository already has one of those files, merge the OBO rules into the existing instructions instead of replacing them. Keep the trigger guidance that explains when OBO is preferred over plain chat.

### Cline

Cline stores MCP server settings in `cline_mcp_settings.json`. A local stdio configuration for `obo-mcp` looks like this:

```json
{
  "mcpServers": {
    "obo-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/warnes-innovations/obo-mcp",
        "obo-mcp"
      ],
      "disabled": false
    }
  }
}
```

For behavior guidance, reuse the same rules from the Copilot or AGENTS template in Cline's workspace instructions or custom prompt setup. Cline's MCP config only exposes the tools; it does not replace explicit workflow instructions. If the target workspace already has Cline instructions, merge the OBO rules into the existing guidance rather than replacing it wholesale.

### Other Agents

If an agent supports a repository instruction file, copy the shared OBO workflow rules into that client's preferred instruction location. If it only supports user-level or UI-defined instructions, paste the same rules there and keep the MCP registration separate. When an instruction file already exists, merge these rules with the existing guidance and resolve any conflicts explicitly.

Minimal rule set to reuse across agents:

- Never directly edit `.github/obo_sessions/*.json` or `index.json`.
- Start with `obo_list_sessions`.
- If an incomplete session exists, ask whether to resume, merge, replace, or
  stop.
- Use `obo_create` for new sessions and `obo_merge_items` to append findings.
- Start OBO work with an overview of scope, item ordering, and major
  dependencies.
- Use `obo_next` to choose work, `obo_mark_in_progress` when starting,
  `obo_mark_blocked` when progress is blocked, and `obo_mark_complete` or
  `obo_mark_skip` when resolving items.
- Use `obo_create_child_session` to step into nested sub-work and
  `obo_complete_child_session` to resume the parent session.
- Use `obo_session_status` or `obo_list_items` to inspect state.
- Use `obo_complete_session` when no actionable items remain.

## Session Format

Session files live at `{base_dir}/.github/obo_sessions/session_YYYYMMDD_HHMMSS.json`. New sessions created through `obo_create` must follow this filename pattern. Existing session files can still be opened by path or filename for read/update operations.

Item statuses are `pending`, `in_progress`, `blocked`, `completed`, and `skipped`. Blocked items store blocker metadata plus `blocked_at` so the reason for the stall is preserved.

Session statuses are `active`, `paused`, and `completed`. A parent session is paused when an active child session exists.

Child sessions store `parent_session_file` and optional `parent_item_id`. Parent sessions track `child_session_files` and `active_child_session` so nested OBO workflows can pause and resume cleanly.

Priority score formula: `urgency + importance + (6 - effort) + dependencies`

Mutating tools keep `index.json` synchronized with session changes.
