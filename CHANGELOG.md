<!--
Copyright (C) 2026 Gregory R. Warnes
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of Oboe MCP.
For commercial licensing, contact greg@warnes-innovations.com
-->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project uses Semantic Versioning.

## [Unreleased]

### Changed

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
