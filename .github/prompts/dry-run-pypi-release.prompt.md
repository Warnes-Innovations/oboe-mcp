---
description: "Run a dry-run oboe-mcp release workflow with tests, packaging validation, and release-prep checks but no push, tag, GitHub release, or PyPI publish"
name: "Dry Run PyPI Release"
argument-hint: "Version, test scope, or dry-run constraints"
agent: "agent"
---
Prepare a dry-run release for `oboe-mcp` without performing any irreversible publication step.

Use the user's chat input as the release target and any constraints, including version, release note focus, or requested validation scope.

Workflow:
1. Inspect the current repository state before making changes.
2. Run the relevant tests first. Prefer the verified repo command `.venv/bin/python -m pytest tests/test_session.py tests/test_server.py` unless the user explicitly requests a different scope.
3. If tests fail, fix release-blocking issues when they are clearly in scope. If anything needs user clarification, approval, or triage, start an OBO session and continue through `/obo`.
4. Complete the necessary release-prep tasks for this repository, including version updates, changelog and README adjustments, and packaging validation.
5. Build and validate the distributable artifacts, and verify that the repository would be ready for tagging and publication.
6. Stop before any irreversible step. Do not run `git push`, create a tag, create a GitHub release, or publish to PyPI.

Execution rules:
- Prefer minimal, targeted edits.
- Do not revert unrelated user changes.
- Treat unrelated dirty-worktree files as out of scope unless they block release readiness.
- If asked to cross the dry-run boundary into any irreversible action, stop and ask whether the user wants to switch to the live publish prompt.

Output:
- Summarize what changed.
- Report the exact version prepared.
- State what was validated and what remains before a live publish.
- Call out any remaining blockers or follow-up actions.