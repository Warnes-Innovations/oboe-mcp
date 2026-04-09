---
description: "Start or resume an /obo session to triage oboe-mcp release blockers, failed tests, packaging issues, or publish workflow problems"
name: "Triage Release Blockers"
argument-hint: "Describe the release blocker, failure, or question to triage"
agent: "agent"
---
Triage an `oboe-mcp` release blocker by using an OBO workflow instead of an ad hoc discussion.

Use the user's chat input as the blocker description, failure mode, or release question.

Workflow:
1. Inspect the current repository and release state relevant to the reported blocker.
2. Create or resume an OBO session for the release issue.
3. Convert the blocker into explicit items with priorities, dependencies, and next actions.
4. Work the items one by one, asking for clarification or approval through the OBO session when needed.
5. Resolve the blocker when possible, or stop with a precise record of what remains blocked and why.

Execution rules:
- Keep the OBO session focused on release readiness, packaging, tests, tagging, publication, or post-release verification.
- Prefer concrete diagnostics over speculation.
- If the blocker reveals a separate nested problem, create a child OBO session and resume the parent after it is resolved.

Output:
- Summarize the blocker and the OBO session used.
- State what was resolved, deferred, or remains blocked.
- Identify the next release action that is safe to take.