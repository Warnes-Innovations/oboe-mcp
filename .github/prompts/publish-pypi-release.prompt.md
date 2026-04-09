---
description: "Test the oboe-mcp package, complete release-prep tasks, publish to PyPI, and use /obo if clarifications or blockers arise"
name: "Publish PyPI Release"
argument-hint: "Version, release scope, or special release instructions"
agent: "agent"
---
Prepare and publish an `oboe-mcp` release for this workspace.

Use the user's chat input as the release target and any special constraints, including version, release notes focus, or whether this is a dry run or live publish.

Workflow:
1. Inspect the current repository state before making changes.
2. Run the relevant tests first. Prefer the verified repo command `.venv/bin/python -m pytest tests/test_session.py tests/test_server.py` unless the user explicitly requests a different scope.
3. If tests fail, fix release-blocking issues when they are clearly in scope. If anything needs user clarification, approval, or triage, start an OBO session and continue the discussion through `/obo` rather than asking ad hoc questions.
4. Complete all necessary release-prep tasks for this repository. This includes version updates, changelog and README adjustments, packaging validation, and any other required release artifacts.
5. Perform the publish flow needed for this repository, including git staging and commits, tags, pushes, GitHub release steps, and verification of the configured publish workflow, when those steps are required and the environment is authenticated.
6. Verify the published result end to end. Confirm PyPI visibility and perform at least one install or resolution check for the released package version.
7. Do not stop at analysis. Carry the release through implementation and verification unless blocked by a real missing prerequisite.

Execution rules:
- Prefer minimal, targeted edits.
- Do not revert unrelated user changes.
- Treat unrelated dirty-worktree files as out of scope unless they block the release.
- Always pause for explicit confirmation immediately before any of these irreversible operations: `git push`, tag creation, GitHub release creation, or PyPI publication. This pause is required even if the user originally said "publish".
- Before asking for that confirmation, summarize the exact action about to happen, the target branch or tag, and the version involved.
- If a blocker or clarification is needed, create or resume an OBO session and present the issue there.

Output:
- Summarize what changed.
- Report the exact version released or attempted.
- State what was verified locally and remotely.
- Call out any remaining risks or follow-up actions.
