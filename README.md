<!--
Copyright (C) 2026 Gregory R. Warnes
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of Oboe MCP.
For commercial licensing, contact greg@warnes-innovations.com
-->

# Oboe MCP

Structured one-by-one workflows for coding agents.

MCP server for durable one-by-one review workflows, with prioritized session state for coding agents.

Provides 16 tools for creating, navigating, and resolving items in priority-scored session files, including blocked-item handling, first-class approval updates, and nested child sessions, so `/obo` workflows can use MCP operations instead of raw JSON edits.

Licensed under `AGPL-3.0-or-later` with commercial licensing available.
See `LICENSE` for full terms.

## Tools

| Tool | Description |
| ---- | ----------- |
| `obo_create` | Create session file + update index.json atomically |
| `obo_list_sessions` | List sessions from index.json |
| `obo_session_status` | Summary stats for a session |
| `obo_next` | Next item: in_progress first, then highest-priority pending, then deferred |
| `obo_list_items` | All items sorted by priority_score desc |
| `obo_get_item` | Full detail for one item |
| `obo_mark_blocked` | Mark an item blocked and store blocker information |
| `obo_mark_complete` | Mark item completed with resolution text |
| `obo_mark_in_progress` | Mark item in progress |
| `obo_mark_skip` | Mark item skipped |
| `obo_set_approval` | Set approval metadata and optional lifecycle state |
| `obo_complete_session` | Mark a session completed when no actionable items remain |
| `obo_create_child_session` | Create a child session, pause the parent, and step into the child |
| `obo_complete_child_session` | Complete a child session and resume the parent |
| `obo_merge_items` | Append new items to an existing session and reactivate it |
| `obo_update_field` | Update any field; auto-recalculates priority_score |

## Why OBO Sessions

One-by-One sessions are not just saved chat notes. They are a workflow model for handling multi-item work as a durable, ordered interaction session.

Compared with plain chat or an agent's built-in follow-up questions, OBO adds capabilities that those lighter interaction modes do not usually provide:

- an overview-first workflow, where the agent can begin with the scope, item count, major categories, and proposed execution order
- explicit reprioritization based on urgency, importance, effort, and dependency pressure instead of whatever order happened to appear in chat
- durable lifecycle states through `pending`, `in_progress`, `deferred`, `blocked`, `completed`, and `skipped`
- separate approval metadata through `approval_status`, `approval_mode`, `approved_at`, and `approval_note`
- stored blocker metadata so blocked work is still visible and explainable instead of silently disappearing from the active queue
- nested child sessions that pause a parent session, handle a sub-problem, then resume the parent session cleanly
- first-class session lifecycle management: list, create, inspect, merge, pause, resume, and close sessions as named workflow objects
- deterministic recovery after model restarts, editor reloads, or agent handoff
- a machine-readable audit trail in session files instead of relying on conversational memory

This matters most when the work spans many findings, requires explicit user approvals, depends on intermediate sub-investigations, or must survive across several agent turns. Chat is good at conversation. A structured question tool is good at getting a clean answer in the current turn. OBO is for durable workflow orchestration.

Use OBO when you need controlled sequential handling, durable queue state, or nested sub-work. Use plain chat when the task is small enough that a full workflow object would add more overhead than value.

## State Model

OBO tracks each item on two independent axes.

### Lifecycle Axis

- `pending`: work is queued but not yet started
- `in_progress`: work is actively being done now
- `deferred`: work is approved for later execution and should stay out of the immediate review queue until the active review pass is exhausted or the user explicitly requests deferred work
- `blocked`: work cannot continue until an external dependency or sub-problem is resolved
- `completed`: work is finished and closed
- `skipped`: work is intentionally not being executed

### Approval Axis

- `unreviewed`: no explicit user decision has been recorded yet
- `approved`: the user has authorized the work
- `denied`: the user has explicitly rejected the work

Approval metadata fields:

- `approval_status`: approval decision for the item
- `approval_mode`: `immediate` or `delayed` when an approval timing decision was recorded
- `approved_at`: timestamp for when approval was recorded
- `approval_note`: optional free-text note about the approval decision

Common pairings:

- Approve Immediate: call `obo_set_approval(..., approval_status="approved", approval_mode="immediate")`; the item normally remains `pending` until work begins or is moved to `in_progress`
- Approve Delayed: call `obo_set_approval(..., approval_status="approved", approval_mode="delayed")`; this records delayed approval and moves the item to `deferred`
- Deny: set `approval_status=denied`; if the item is being closed out of the queue, pair it with `status=skipped`

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

Suppose an agent reviews a small toy to-do app and finds five items in this raw discovery order:

1. Improve an ambiguous settings label in the UI.
2. Resolve a race condition in the background sync job.
3. Add a regression test for duplicate task IDs.
4. Add missing input validation on the create-task endpoint.
5. Fix password logging in the login handler.

#### Standard chat

**Agent:**

> I found five issues in the toy app:
> Issue 1: Improve an ambiguous settings label in the UI.
> Issue 2: Resolve a race condition in the background sync job.
> Issue 3: Add a regression test for duplicate task IDs.
> Issue 4: Add missing input validation on the create-task endpoint.
> Issue 5: Fix password logging in the login handler.
>
> What do you want to do next?

**User:**

> Do 4 and 2 first.

**Commentary**:

- This is fast, but the chat itself becomes the only record of the sequence, the dependency between items 4 and 3 is implicit.
- The status of the other issues is not captured, and the user will need to explicitly request that the agent display or work on the other issues.
- If the session is interrupted, another agent would have to reconstruct state from the transcript.

#### askQuestions-style chat

**Agent:**

> I found five issues. Which should we do first?
>
> Options:
> • 4. Add missing input validation on the create-task endpoint
> • 2. Resolve a race condition in the background sync job
> • 5. Fix password logging in the login handler
> • 3. Add a regression test for duplicate task IDs
> • 1. Improve an ambiguous settings label in the UI

**User:**

> 4

**Agent:**

> Next action?
>
> Options:
> • Continue with 2
> • Reorder the remaining list
> • Stop

**Commentary**:

- This gives cleaner user choices than plain chat, but the tool still does not create a durable, dependency-aware workflow object by itself.
- The status of the other issues is still not captured, and the user will need to explicitly request that the agent display or work on the other issues.
- Likewise, if the session is interrupted, another agent would have to reconstruct state from the transcript.

#### One-by-One session

Following the OBO agent prompt instructions, the agent assigns this ordering logic:

- Item 4 goes first because the create-task endpoint behavior should be stabilized before the follow-up regression test is written.
- Item 2 comes next because the race condition can affect correctness across the sync flow and may require a nested investigation session.
- Item 5 follows because it is an important security fix, but it does not block the validation and concurrency work.
- Item 3 stays behind item 4 because the regression test should lock in the final validation behavior instead of preceding it.
- Item 1 is still useful, but it is low impact compared with the other four items, so it comes last.

**Agent:**

> I created an OBO session for 5 findings.
>
> **Executive summary:**
> • Total items: 5
> • Categories: 1 API correctness, 1 concurrency, 1 security, 1 testing, 1 UX
> • Priority order: 4, 2, 5, 3, 1
> • Estimated effort: 11
> • Critical items: 3
> • Dependency note: item 3 follows item 4 so the regression test targets the stabilized endpoint behavior
> • Child-session note: item 2 may branch into a nested investigation session
> • Current session state: 5 pending, 0 in progress, 0 completed
>
> **Current item:**
> • Item 4
> • Title: Add missing input validation on the create-task endpoint
> • Category: API correctness
> • Priority score: 18
> • Rationale: stabilize the endpoint contract before the follow-up regression test is addressed
>
> **Reply with one of these:**
> • Approve Immediate
> • Approve Delayed
> • Deny
> • Next
> • More Options

**User:**

> Approve Immediate

 [ ... agent does the item 4 work here ... ]

**Agent:**

> **Item 4 completed.**
>
> **Session status:**
> • 1 completed
> • 4 pending
> • 20% done
>
> **Current item:**
> • Item 2
> • Title: Resolve a race condition in the background sync job
> • Category: Concurrency
> • Priority score: 15
> • Rationale: this can affect correctness across the sync flow and may need a nested investigation before the parent item can be resolved
>
> **Child-session note:**
> • If you approve immediate, I will present the nested flow
>
> **Reply with one of these:**
> • Approve Immediate
> • Approve Delayed
> • Deny
> • Next
> • More Options

**User:**

> Approve Immediate.

**Agent:**

> Item 2 needs isolated investigation before I can finish it. I created a child OBO session for the race-condition investigation and paused the parent session.
>
> **Child session summary:**
> • Scope: reproduce the sync race, identify the conflicting code path, and verify a fix.
> • Proposed child order: reproduce, isolate, patch, verify.

**User:**

> Proceed.

[ ... agent does the child-session investigation work here ... ]

**Agent:**

> **Child session completed.** Root cause was overlapping writes from two sync workers.
>
> I resumed the parent session, applied the fix, and I am ready to complete item 2.
>
> **Current item:**
> • Item 2
> • Title: Resolve a race condition in the background sync job
> • Category: Concurrency
> • Priority score: 15
>
> **Reply with one of these:**
> • Approve Immediate
> • Approve Delayed
> • Deny
> • Next
> • More Options

**User:**

> Approve Immediate

**Agent:**

> [ ... agent records the resolution and resumes the parent workflow here ... ]
>
> **Item 2 completed.**
>
> **Session status:**
> • 2 completed
> • 3 pending
> • 40% done
>
> **Current item:**
> • Item 5
> • Title: Fix password logging in the login handler
> • Category: Security
> • Priority score: 15
> • Rationale: remove plaintext password logging without disturbing the validation and race-condition fixes
>
> **Reply with one of these:**
> • Approve Immediate
> • Approve Delayed
> • Deny
> • Next
> • More Options

**User:**

> Proceed.

**Agent:**

> [ ... agent does the item 5 work here ... ]
>
> **Item 5 completed.**
>
> **Session status:**
> • 3 completed
> • 2 pending
> • 60% done
>
> **Current item:**
> • Item 3
> • Title: Add a regression test for duplicate task IDs
> • Category: Testing
> • Priority score: 14
> • Rationale: this now follows item 4 as planned, because the endpoint behavior has been stabilized
>
> **Reply with one of these:**
> • Approve Immediate
> • Approve Delayed
> • Deny
> • Next
> • More Options

**User:**

> Proceed.

**Agent:**

> [ ... agent does the item 3 work here ... ]
>
> **Item 3 completed.**
>
> **Session status:**
> • 4 completed
> • 1 pending
> • 80% done
>
> **Current item:**
> • Item 1
> • Title: Improve an ambiguous settings label in the UI
> • Category: UX
> • Priority score: 10
> • Rationale: this is the remaining low-impact cleanup item
>
> **Reply with one of these:**
> • Approve Immediate
> • Approve Delayed
> • Deny
> • Next
> • More Options

**User:**
> Approve Immediate

[ ... agent does the item 1 work here ... ]

**Agent:**

> **Item 1 completed.**
>
> **Session status:**
> • 5 completed
> • 0 pending
> • 100% done
>
> **All actionable items are now resolved.** I completed the OBO session and the final record includes the child-session detour, the dependency-aware ordering, and the resolution for each item.

**Commentary**: this preserves the reordered plan, stores the dependency constraint, allows item 2 to branch into a child session, and gives another agent a durable session state to resume later.

## Installation

### Automated Installation

Run the interactive installer from this repository:

```bash
./install.sh
```

The installer:

- asks which client or clients you want to configure: Copilot, Codex, Claude Code, Cline, or all of them
- asks whether to install shared workflow instructions at the user level when supported or into a target project
- writes the `oboe-mcp` MCP server entry into each client's real config file
- installs the packaged OBO instructions, prompt, and skill files into the matching destination
- explains what it is changing and makes timestamped backups before it updates existing files

The automated installer uses the current checkout path in `uvx --from ...`, so it is best when you are installing from a local clone of this repository.

If you want clients to install `oboe-mcp` from the published GitHub URL instead of a local checkout, follow the manual steps below.

### Manual Installation

Install the MCP server first so your agent can call the `obo_*` tools. Then install the shared OBO instructions so your agent knows when to use those tools and how to follow the workflow correctly.

If you are wiring up an MCP config by hand, point it at either your local checkout or the published GitHub URL.

Local checkout example:

```json
"oboe-mcp": {
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "/absolute/path/to/oboe-mcp", "oboe-mcp"]
}
```

Published GitHub URL example:

```json
"oboe-mcp": {
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "git+https://github.com/warnes-innovations/oboe-mcp", "oboe-mcp"]
}
```

This repository includes reusable templates under `templates/agent-setup/`:

- `templates/agent-setup/copilot/copilot-instructions.md`
- `templates/agent-setup/copilot/skills/one-by-one/SKILL.md`
- `templates/agent-setup/copilot/prompts/obo.prompt.md`
- `templates/agent-setup/AGENTS.md`
- `templates/agent-setup/CLAUDE.md`

Registering `oboe-mcp` only exposes the `obo_*` tools. It does not by itself guarantee the overview-first, dependency-aware, one-item-at-a-time workflow shown in the toy example above. To make agent behavior reliable, install both parts:

- the MCP server registration, so the agent can call the tools
- the shared OBO instructions, so the agent knows when to switch from plain chat or a simple question tool into a real OBO session

Across clients, the same pattern applies:

1. Register `oboe-mcp` in the client's MCP configuration.
2. Copy or merge the packaged OBO instructions into the client's instruction location.
3. Keep existing repository guidance and merge the OBO rules into it instead of overwriting it.
4. Expect the installed instructions to tell the agent when OBO is preferred over plain chat, how to start with an overview, how to resume or merge existing sessions, and how to avoid direct JSON edits.

#### GitHub Copilot

For Copilot, register `oboe-mcp` in your VS Code MCP config and then copy the packaged OBO files into either your VS Code user configuration or the target repository's `.github/` folder.

Without those installed files, Copilot may still use plain chat or `askQuestions`-style interaction even though the MCP tools are available. The packaged instruction, skill, and prompt files are what push Copilot toward the full OBO workflow.

VS Code MCP config files are normally stored in the same user configuration folder as `copilot-instructions.md`. Add an `oboe-mcp` entry to `mcp.json` with either your local checkout path or the published GitHub URL.

VS Code user configuration folders:

- macOS: `$HOME/Library/Application Support/Code/User`
- Linux: `$HOME/.config/Code/User`
- Windows: `$HOME/AppData/Roaming/Code/User`

Install the packaged Copilot files in one of these two ways:

User-level installation:

- Copy or merge `templates/agent-setup/copilot/copilot-instructions.md` into your user-level `copilot-instructions.md`
- Copy or merge `templates/agent-setup/copilot/skills/one-by-one/SKILL.md` into `skills/one-by-one/SKILL.md`
- Copy or merge `templates/agent-setup/copilot/prompts/obo.prompt.md` into `prompts/obo.prompt.md`

Repository-level installation:

- Copy or merge `templates/agent-setup/copilot/copilot-instructions.md` into the target repository's `.github/copilot-instructions.md`
- Copy or merge `templates/agent-setup/copilot/skills/one-by-one/SKILL.md` into the target repository's `.github/skills/one-by-one/SKILL.md`
- Copy or merge `templates/agent-setup/copilot/prompts/obo.prompt.md` into the target repository's `.github/prompts/obo.prompt.md`

Use user-level installation when you want the OBO workflow available across repositories. Use repository-level installation when you want the workflow to travel with a specific project.

If the destination file already exists, merge the OBO rules into it instead of overwriting it. Adjust the wording where needed so the OBO instructions fit the project's existing review rules and conventions.

The `templates/agent-setup/copilot/` folder in this repository is only the source package. Copilot will only discover the files after you install them into your VS Code user configuration folders or into the target repository's `.github/` folder.

The Copilot instruction template tells agents to:

- avoid direct edits to `.github/obo_sessions/*.json`
- use OBO when the user asks for one-by-one handling, when multiple findings need explicit sequential approval, or when resumable queue state is needed
- use `obo_list_sessions`, `obo_create`, `obo_merge_items`, `obo_next`,
  `obo_mark_in_progress`, `obo_mark_blocked`, `obo_mark_complete`,
  `obo_mark_skip`, `obo_create_child_session`,
  `obo_complete_child_session`, `obo_session_status`, and
  `obo_complete_session`
- use a structured question tool for predefined OBO choices such as resume, merge, replace, approval, navigation, reorder, restore, and stop
- ask the user whether to resume, merge, replace, or stop when an active session already exists
- only fall back to plain text when the structured question tool is unavailable, failing, or the response truly must be freeform, and explicitly state that reason

The packaged skill provides the trigger logic for when OBO should be used, and the prompt template provides an on-demand `/obo` workflow that walks an agent through the full sequential session lifecycle using the MCP server.

#### Codex

For Codex, the same two-part pattern applies: register the MCP server in `~/.codex/config.toml`, then copy or merge the shared OBO instruction template into the target repository's `AGENTS.md`.

Register `oboe-mcp` in `~/.codex/config.toml`:

```toml
[mcp_servers.oboe-mcp]
command = "uvx"
args = ["--from", "git+https://github.com/warnes-innovations/oboe-mcp", "oboe-mcp"]
```

Replace the GitHub URL with your local checkout path if you want Codex to run from a clone you already have on disk.

Then copy or merge `templates/agent-setup/AGENTS.md` into the target repository as `AGENTS.md`. If `AGENTS.md` already exists, merge the OBO rules into the existing file instead of replacing it.

The packaged `AGENTS.md` template tells Codex to:

- switch from normal chat into OBO when the work needs durable queue state, explicit sequential approval, reordering, blocker tracking, or nested child sessions
- start with `obo_list_sessions` and ask whether to resume, merge, replace, or stop when an incomplete session already exists
- begin each OBO session with an overview of scope, dependencies, and proposed order instead of jumping straight into the first item
- use the MCP tools as the source of truth for session state rather than editing session JSON directly
- use the agent's structured question UI/tool by default for predefined OBO menus and explain any plain-text fallback

#### Claude Code

For Claude Code, register the MCP server in `~/.claude/settings.json` or by using the Claude CLI, and then copy the shared OBO instructions into `CLAUDE.md` or `.claude/CLAUDE.md` in the target repository.

As with Copilot and Codex, the MCP registration only exposes the tools. The instruction file is what tells Claude Code when OBO is preferable to plain chat and how the session flow should behave.

JSON config example for `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "oboe-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/warnes-innovations/oboe-mcp", "oboe-mcp"]
    }
  }
}
```

Register `oboe-mcp` in Claude Code:

```bash
claude mcp add --transport stdio --scope project oboe-mcp -- \
  uvx --from git+https://github.com/warnes-innovations/oboe-mcp oboe-mcp
```

Then copy or merge `templates/agent-setup/CLAUDE.md` into the target repository as `CLAUDE.md` or `.claude/CLAUDE.md`. If one of those files already exists, merge the OBO rules into the existing instructions instead of replacing them.

The packaged Claude template tells Claude Code to:

- use OBO for multi-item review flows that need durable state, explicit approvals, reordering, blockers, or nested child sessions
- open with a summary of scope, major dependencies, and proposed order
- keep the session updated after each approved action instead of letting the chat transcript become the only record
- stop and surface a tool gap if a needed OBO action is not available through MCP
- use the agent's structured question UI/tool by default for predefined OBO menus and explain any plain-text fallback

#### Cline

For Cline, register the MCP server in `cline_mcp_settings.json` and then copy or merge the OBO instructions into your Cline workspace guidance.

This follows the same pattern as the other clients: MCP registration exposes the tools, while the instruction text tells Cline when to use a durable OBO workflow instead of a lighter prompt or chat interaction.

A local stdio configuration for `oboe-mcp` looks like this:

```json
{
  "mcpServers": {
    "oboe-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/warnes-innovations/oboe-mcp",
        "oboe-mcp"
      ],
      "disabled": false
    }
  }
}
```

On macOS, the default VS Code Cline MCP settings path is `$HOME/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`. On Linux it is `$HOME/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`. On Windows it is `$HOME/AppData/Roaming/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`.

After registering the server, copy or merge the same rules from the Copilot or AGENTS template into Cline's workspace instructions or custom prompt setup. Cline's MCP config only exposes the tools; it does not replace explicit workflow instructions. If the target workspace already has Cline instructions, merge the OBO rules into the existing guidance rather than replacing it wholesale.

The installed Cline guidance should tell the agent to:

- use OBO when work needs persistent queue state rather than a one-turn menu
- start with a summary and proposed order before presenting the first item
- update the stored session after each approval, skip, block, or completion
- avoid direct edits to `.github/obo_sessions/*.json` and `index.json`
- use Cline's structured question UI/tool by default for predefined OBO menus and explain any plain-text fallback

#### Other Agents

If you are installing OBO for another agent, copy the shared OBO workflow rules into that client's preferred instruction location. If the agent only supports user-level or UI-defined instructions, paste the same rules there and keep the MCP registration separate. When an instruction file already exists, merge these rules with the existing guidance and resolve any conflicts explicitly.

The goal is to reproduce the same behavior described earlier in this README:

- plain chat remains available for small single-step tasks
- question tools remain available for short menu choices in the current turn
- OBO becomes the preferred mode when the work needs a durable ordered queue, explicit approvals, dependency-aware ordering, blocker tracking, or nested child sessions

Minimal rule set to reuse across agents:

- Never directly edit `.github/obo_sessions/*.json` or `index.json`.
- Start with `obo_list_sessions`.
- If an incomplete session exists, use a structured question tool when
  available to ask whether to resume, merge, replace, or stop.
- Use `obo_create` for new sessions and `obo_merge_items` to append findings.
- Start OBO work with an overview of scope, item ordering, and major
  dependencies.
- Use a structured question tool by default for predefined OBO menus such as
  approval, navigation, reorder, restore, and stop.
- Only fall back to plain text when no structured question tool exists, the
  tool is failing, or the response truly must be open-ended, and say why.
- Present one item at a time and wait for explicit user approval before moving
  on.
- Use `obo_next` to choose work, `obo_mark_in_progress` when starting,
  `obo_mark_blocked` when progress is blocked, and `obo_mark_complete` or
  `obo_mark_skip` when resolving items.
- Use `obo_create_child_session` to step into nested sub-work and
  `obo_complete_child_session` to resume the parent session.
- Use `obo_session_status` or `obo_list_items` to inspect state.
- Use `obo_complete_session` when no actionable items remain.

Session file paths, filename rules, JSON fields, status semantics, priority scoring, and the `index.json` summary format are documented in [docs/SESSION_FORMAT.md](/Users/warnes/src/oboe-mcp/docs/SESSION_FORMAT.md).
