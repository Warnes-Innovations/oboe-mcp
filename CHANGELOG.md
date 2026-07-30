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

## [0.3.0] - 2026-04-22

### Breaking Changes

- **All MCP tool names renamed from `obo_*` to `oboe_*`** to match the package
  name (`oboe-mcp`) and CLI name (`oboe-cli`). Existing agent instruction files,
  prompts, and skill definitions that reference `obo_create`, `obo_next`, etc.
  must be updated. Run `inst/migrate-to-oboe.sh` (see below) to automate this.

- **Session directory renamed from `.github/obo_sessions/` to
  `.github/oboe_sessions/`**. A backward-compatible symlink
  `obo_sessions → oboe_sessions` is created automatically by the migration
  script and is present in the oboe-mcp repo itself. Existing tooling that
  hard-codes the old path will continue to work via the symlink.

### Migration

```bash
# From PyPI (no install required)
uvx oboe-mcp migrate /path/to/your/project

# Or run the script directly from a local checkout
bash inst/migrate-to-oboe.sh /path/to/your/project
```

The script:
1. Renames `.github/obo_sessions/` → `.github/oboe_sessions/` and creates a
   `obo_sessions` symlink for backward compatibility.
2. Updates all agent instruction files (`.github/copilot-instructions.md`,
   `CLAUDE.md`, `AGENTS.md`, `SKILL.md`, `*.prompt.md`) to use `oboe_` tool
   names and `oboe_sessions` paths.
3. Prints a summary of every file changed.

### Added

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

- Server module docstring updated to reflect 20 tools.
- `_open_count` import moved from inline (inside `oboe_cancel_session`) to the
  module-level import block.
- `obo_set_approval` parameter `note` → `approval_note`.
- `obo_cancel_session` parameter `reason` → `cancel_reason`.
- `obo_create` / `obo_create_child_session` parameter `session_filename` →
  `session_file`.
- `oboe-cli approve`: `--mode` → `--approval-mode`, `--note` → `--approval-note`.

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
