---
description: "Use when testing, preparing, tagging, releasing, or publishing oboe-mcp package versions. Covers repo-specific release commands, verification steps, and confirmation boundaries for push, tags, GitHub releases, and PyPI publication."
name: "Oboe Release Workflow"
---
# Oboe MCP Release Workflow

- Treat release work in this repository as a staged workflow: inspect repo state, run tests, complete release-prep edits, validate packaging, then handle remote release steps.
- Prefer the verified test command `.venv/bin/python -m pytest tests/test_session.py tests/test_server.py` unless the user requests a different scope.
- Keep release edits minimal and targeted. Do not revert unrelated dirty-worktree files unless the user explicitly asks.
- Before any irreversible action, pause for confirmation even if the user's initial request already said to publish.
- The required confirmation boundary includes each of these actions: `git push`, tag creation, GitHub release creation, and PyPI publication.
- When asking for confirmation, summarize the exact action, the version, and the branch or tag involved.
- After a live publish, verify the result end to end: release workflow status, PyPI visibility, and at least one package resolution or install check.
- If clarification, triage, or blocker handling is needed, prefer creating or resuming an OBO session rather than handling it as an unstructured side conversation.