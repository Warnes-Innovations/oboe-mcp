<!--
Copyright (C) 2026 Gregory R. Warnes
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of Oboe MCP.
For commercial licensing, contact greg@warnes-innovations.com
-->

# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project uses Semantic Versioning.

## [Unreleased]

### Fixed

- **A non-numeric priority factor crashed the server instead of being
  rejected** ([#20](https://github.com/Warnes-Innovations/oboe-mcp/issues/20)).
  `_recalc_priority` added caller-supplied `urgency`/`importance`/`effort`/
  `dependencies` straight into the `priority_score` arithmetic, so a string
  `dependencies` surfaced to the MCP client as
  `unsupported operand type(s) for +: 'int' and 'str'` — naming neither the
  offending item nor the offending field.

  Two independent layers now close it:

  - **Validation at the input boundary.** `validate_score_components()` runs
    on every caller-supplied item before anything is written, and rejects a
    bad value with `item 'example': 'dependencies' must be a number 0-5 (got
    str: '...')`. Applied in `create_session`, `merge_items`,
    `create_child_session` and `update_field` — i.e. `oboe_create`,
    `oboe_merge_items`, `oboe_create_child_session` and `oboe_update_field`.
    Validation happens *before* the transaction opens, so a rejected batch
    writes nothing and appends nothing. As a second layer, the arithmetic
    itself now checks each component's type, so no route into it — including
    an old session file — can produce a bare `TypeError`.
  - **The contract is documented.** The `items` JSON schema published by
    `oboe_create`, `oboe_merge_items` and `oboe_create_child_session` now
    types the four factors as `number` with `minimum: 0` / `maximum: 5`, and
    states that `dependencies` is dependency *pressure* as a number rather
    than a description of what the item depends on — the misreading its name
    invites. The tool descriptions, `docs/SESSION_FORMAT.md`, and the
    `/obo` workflow prompt say the same.

  Booleans, containers, `null`, fractional floats and — at the JSON tools —
  numeric strings are all rejected rather than coerced. `oboe_update_field`
  and `oboe-cli update` still accept a numeric string, because their `value`
  arrives from `argv` or a `str`-typed MCP parameter; a non-numeric one is
  now rejected by name instead of by `invalid literal for int()`.

  The 0-5 range is enforced on **input only**. Nothing ever bounded these
  values on disk, so applying the range to the load path would make a
  previously readable session file unloadable.

- **`trim_sessions` deleted files outside the sessions directory.** It joined
  each `index.json` row's `file` onto the sessions directory and unlinked the
  result, unchecked. A row of `../../IMPORTANT.txt` destroyed that file and
  still reported it as a deleted session. `index.json` is routinely committed
  and synced between machines, so its contents are not this code's to trust.

  `_deletable_session` now applies three independent checks and refuses on any
  one: the name must match `session_YYYYMMDD_HHMMSS.json`, must be a bare
  filename, and must resolve with the sessions directory as its parent — the
  last being what catches a symlink pointing out of the tree, which neither
  name check can see. Refused rows are reported under a new `rejected` key
  rather than dropped, and `deleted` now lists what was actually unlinked
  instead of what was selected (a row with no `file` was previously counted as
  a deletion that never happened).

- **`oboe_create` accepted duplicate item ids; `oboe_merge_items` rejected
  them.** A second item sharing an id is unreachable — every lookup resolves
  to the first — so it could never be completed or skipped and the session
  could never finish. Worse, `oboe_next(mark_in_progress=True)` returned the
  shadowed item and then marked the *other* one in progress. Both paths now
  share `_stage_items`, which validates ids, rejects duplicates, and assigns
  auto-ids only after every explicit id in the batch is known — so `[{},
  {"id": 1}]` no longer produces two items numbered 1. An id must be a string
  or an integer; `null` is rejected with a message saying to omit the field.

- **`oboe_update_field` could rewrite `id` into a collision, and accepted any
  field name at all.** Setting `id` is now refused outright, and the field
  name is checked against the documented item schema instead of being written
  through.

- **`oboe_trim_sessions` crashed on a timezone-aware `before`.** `created` is
  parsed from a bare `YYYY-MM-DD` and is naive, so an ISO-8601 string with an
  offset — the likeliest form for a machine to emit — raised
  `TypeError: can't compare offset-naive and offset-aware datetimes` from
  inside a delete operation. An aware cutoff is now converted to local naive.

- **A session holding both string and integer item ids crashed `oboe_next`
  and `oboe_list_items`.** `id` is documented as "string or integer" and both
  `oboe_create` and `oboe_merge_items` accept whatever the caller supplies, so
  one session can legitimately hold `2` and `"phase-1"`. Both sort keys ended
  in the raw id, so ordering them raised
  `TypeError: '<' not supported between instances of 'int' and 'str'`.

  It stayed latent because the id is only a *tie-break* on `priority_score`:
  a mixed-id session works until two of its items happen to score the same,
  and then every listing of it fails at once. `_id_sort_key` now gives a total
  order — numeric ids first and in numeric order (a string that spells a
  number counts as that number, matching how `merge_items` already picks the
  next id), then the rest as text.

- **The same class in `oboe-cli status`.** `category` is free-form and never
  type-checked, so `sorted(categories.items())` crashed identically on a
  session mixing `5` with `"General"` — taking down a read-only display. It
  now sorts on `str()` of the key.

- **`oboe-cli next --mark-in-progress` crashed on a session with no actionable
  items.** `_cmd_next` dereferenced `item["id"]` before `_print_next`'s
  `item is None` branch could report "No actionable items", so `get_next()`
  returning `None` raised `TypeError: 'NoneType' object is not subscriptable`.
  The MCP `oboe_next` was already correct. All four `get_next`/`get_item` call
  sites were checked; this was the only one missing its guard.

### Added

- **`reindex` — rebuild `index.json` from the session files on disk.** Available
  as the `oboe_reindex` MCP tool and the `oboe-cli reindex` command, with a
  `--check` / `write=False` mode that reports drift and exits non-zero without
  writing (suitable for CI or a pre-commit hook).

  Every pre-existing index repair is *conditional*: `_upsert_index` and
  `list_sessions` rebuild only when the index is missing, corrupt, or
  structurally invalid. That left one failure mode uncovered — an index that is
  perfectly **valid** but no longer **complete**. Because `_is_valid_index`
  returns True for it, `list_sessions` takes the fast path and returns the stale
  subset; nothing repairs it and nothing reports it.

  Found in `agent-config` on 2026-07-31: a tracked `index.json` was reverted to
  an older committed revision, leaving it listing **1 session while 12 existed
  on disk**. Several of the unlisted sessions had open items. They were
  invisible to every tool while their files sat intact in the same directory.

  `reindex` reports what changed (`added` / `removed` / `updated`, before/after
  counts, and any unreadable session files) rather than repairing silently, so
  drift is visible after the fact instead of merely gone.

## [0.3.0] - 2026-07-31

### Breaking Changes

- **All MCP tool names renamed from `obo_*` to `oboe_*`** to match the package
  name (`oboe-mcp`) and CLI name (`oboe-cli`). Existing agent instruction files,
  prompts, and skill definitions that reference `obo_create`, `obo_next`, etc.
  must be updated. Run `oboe-mcp migrate` (see below) to automate this.

- **Session directory renamed from `.github/obo_sessions/` to
  `.github/oboe_sessions/`**. A backward-compatible symlink
  `obo_sessions → oboe_sessions` is created automatically by the migration
  script and is present in the oboe-mcp repo itself. Existing tooling that
  hard-codes the old path will continue to work via the symlink.

### Migration

```bash
# From PyPI (no install required)
uvx oboe-mcp migrate /path/to/your/project

# Preview without changing anything
uvx oboe-mcp migrate /path/to/your/project --dry-run

# Or from a local checkout, with no dependencies installed
python -m oboe_mcp.migrate /path/to/your/project
```

The migration is pure Python and imports only the standard library, so it
works from a plain `pip`/`uvx` install or a bare source checkout — no bash,
perl, or MCP SDK required.

It:
1. Renames `.github/obo_sessions/` → `.github/oboe_sessions/` and creates a
   `obo_sessions` symlink for backward compatibility.
2. Updates all agent instruction files (`.github/copilot-instructions.md`,
   `CLAUDE.md`, `AGENTS.md`, `SKILL.md`, `*.prompt.md`) to use `oboe_` tool
   names and `oboe_sessions` paths.
3. Prints a summary of every file changed.

### Added

- **Cross-process concurrency control for session storage.** Session files are
  shared between the MCP server, `oboe-cli`, and any other process pointed at
  the same project. All reads and writes now go through a cross-process
  reader/writer lock over the sessions directory, and every write is atomic
  (temp file + `os.replace`). This closes six races that could previously lose
  data: lost updates, reading a truncated file mid-write, the session file and
  `index.json` disagreeing, a creation TOCTOU, index-rebuild races, and
  deletion races in `trim_sessions`. Readers take a shared lock and still run
  in parallel. No new runtime dependencies.
- **Caller-selectable lock policy.** The default is to wait up to 30s and then
  raise an error naming the lock file and its holder. Callers preferring to
  retry rather than stall can choose fail-fast, via the new
  `oboe_set_lock_policy` / `oboe_get_lock_policy` MCP tools, the
  `--lock-timeout` / `--lock-fail-fast` CLI flags, or the `OBOE_LOCK_POLICY` /
  `OBOE_LOCK_TIMEOUT` environment variables. See the *Concurrency* section of
  `README.md`.
- `CONTRIBUTING.md`, documenting the branch model, worktree convention, test
  commands, and release confirmation boundaries.
- New MCP tools: `oboe_get_session`, `oboe_mark_deferred`, `oboe_cancel_session`,
  `oboe_trim_sessions`.
- `oboe_next`: `mark_in_progress` param marks item in-progress atomically;
  returns a `progress` dict.
- `oboe_complete_session`: now returns `completed`, `skipped`, and `total` counts.
- `oboe-cli sessions --active`: shorthand for `--status active`.
- `oboe-cli show --fields id,title,status`: limits output to named fields.
- `oboe-cli complete --resolution TEXT`: `--resolution` is now a required flag
  (positional form removed).
- `oboe-cli status --compact`: single-line summary.
- `oboe-cli next --mark-in-progress`: mark item in-progress as part of fetch.

### Changed

- Migrated to MCP Python SDK 2.0 (`mcp>=2.0,<3`): `FastMCP` renamed to
  `MCPServer` in `server.py`; `pyproject.toml`/`uv.lock` updated accordingly.
  Tool decorator API, `mcp.run()`, and all tool registrations are unaffected.
- Server module docstring updated to reflect 22 tools.
- `_open_count` import moved from inline (inside `oboe_cancel_session`) to the
  module-level import block.
- `obo_set_approval` parameter `note` → `approval_note`.
- `obo_cancel_session` parameter `reason` → `cancel_reason`.
- `obo_create` / `obo_create_child_session` parameter `session_filename` →
  `session_file`.
- `oboe-cli approve`: `--mode` → `--approval-mode`, `--note` → `--approval-note`.

### Fixed

- **`__version__` no longer disagrees with the packaged version.**
  `src/oboe_mcp/__init__.py` was left at `0.1.2` when `pyproject.toml` moved to
  `0.2.0`, so the released 0.2.0 reported `oboe_mcp.__version__ == "0.1.2"`.
  Both sources are now `0.3.0` and must be updated together.
- **The migration now works at all, and works everywhere.** It was previously
  a shell script, `inst/migrate-to-oboe.sh`, with two independent defects.
  It was not packaged — shipping in neither the sdist nor the wheel — so
  nobody who installed from PyPI had a copy, while the documented
  `uvx oboe-mcp migrate` command did not exist. And it relied on three
  GNU/bash-4 constructs absent from a stock macOS (`declare -A` — macOS ships
  bash 3.2 — GNU `sed -i EXPR` with `\b`, and `md5sum`), aborting *after*
  renaming the session directory but *before* rewriting any instruction file,
  which left projects half-migrated.

  The migration is now pure Python in `oboe_mcp.migrate`, ships in the wheel,
  and is covered by tests. The shell script has been removed rather than
  fixed: a second implementation of the same rewrite rules can only drift,
  and anyone able to run oboe-mcp already has Python.

### Security

- **Pinned every GitHub Actions dependency to a commit SHA.** `publish.yml`
  used the mutable branch ref `pypa/gh-action-pypi-publish@release/v1` plus
  floating major tags in jobs holding `id-token: write` (PyPI Trusted
  Publishing); `codeql.yml` floated likewise while holding
  `security-events: write`. A repointed ref could have injected code into a
  workflow carrying live publish credentials.
- Raised `codeql.yml` to `actions/checkout` v6 and CodeQL Action v4, clearing
  two runner deprecations: Node 20 is deprecated on GitHub runners, and CodeQL
  Action v3 is scheduled for removal in December 2026. Every action across both
  workflows now runs on node24 (`pypa/gh-action-pypi-publish` is a composite
  action with no Node runtime).

## [0.2.0] - 2026-04-11

### Added

- `oboe-cli` command-line tool installed alongside `oboe-mcp`, providing a human-friendly CLI for the same session files the MCP tools operate on.
- 16 `oboe-cli` subcommands: `sessions`, `status`, `create`, `merge`, `complete-session`, `list`, `next`, `show`, `complete`, `skip`, `in-progress`, `block`, `approve`, `update`, `create-child`, `complete-child`.
- `resolve_base_dir()` in `session.py` for auto-detecting the project root from the current working directory.
- 77 unit tests for `oboe-cli` covering all commands and error paths.
- CLI reference section in README with command table, global options, and quick-start examples.
- `obo_helper.py` replaced with a thin deprecation shim that delegates to `oboe-cli`.

### Changed

- `install.sh` now mentions `oboe-cli` in both the plan and completion summary.

## [0.1.2] - 2026-04-08

### Added

- Release workflow prompt files and shared agent-setup guidance for publishing, dry runs, and blocker triage.

### Changed

- The installer now copies release workflow instructions into the Copilot agent setup.
- The console entry point now provides a proper fast-exit help path, so `oboe-mcp --help` prints usage text instead of starting the MCP server.

## [0.1.1] - 2026-04-08

### Added

- First-class session lifecycle tools for marking items in progress, merging items, and completing sessions.
- Session filename validation for newly created sessions.
- End-to-end workflow coverage for the OBO MCP server.
- Distributable agent setup templates under `templates/agent-setup/`.
- Cross-agent setup guidance for Copilot, Codex, Claude Code, and Cline.
- First-class approval metadata support on items, including `approval_status`, `approval_mode`, `approved_at`, and `approval_note`.
- New `obo_set_approval` MCP tool for recording approval decisions and delayed-review lifecycle transitions in one operation.
- Trusted publishing workflow for TestPyPI and PyPI.
- Release documentation for building, validating, and publishing Python distributions.

### Changed

- Session mutations now keep `index.json` synchronized.
- Session completion state is derived and persisted consistently.
- Package metadata and tests were cleaned up to reduce editor diagnostics.
- Item lifecycle now distinguishes `deferred` from immediate actionable work, while session status reports approval counts separately.
- `items` is now optional (defaults to `[]`) in `obo_create` and `obo_create_child_session`, enabling a two-step workflow where a session is created first and items are added later via `obo_merge_items`. This also ensures the `items` argument is correctly advertised in the published MCP schema for clients that introspect tool parameters.
- Package metadata now includes PyPI-ready project URLs, classifiers, README rendering, and explicit build exclusions for generated cache directories.

## [0.1.0]

### Initial Release

- Initial OBO MCP server with session creation, listing, item navigation, and item update tools.

<!-- markdownlint-enable MD024 -->
