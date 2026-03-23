# LinkedIn Post Draft

We built a small MCP server for a problem that comes up constantly with coding agents: handling multi-item work without losing track of what was already reviewed, approved, blocked, skipped, or deferred.

The approach is called One-by-One review sessions.

Instead of relying on a long chat transcript, the agent stores a real session with an overview, prioritized items, explicit state, blocker metadata, and resumable workflow history. That makes it much easier to review findings one at a time, pause, step into a nested sub-session, come back later, or hand the work to another agent without reconstructing context from memory.

Why it matters:

- better than a flat wall of findings in chat
- more durable than a single turn of question buttons
- supports explicit reprioritization based on impact and dependencies
- preserves blocked state with blocker details instead of losing stalled work
- supports nested child sessions for sub-investigations
- easier to resume after model restarts or editor reloads
- clearer approval flow for code review, planning, and issue triage

We packaged it as `obo-mcp`, with templates for Copilot, Codex, Claude Code, and Cline so teams can adopt the workflow model instead of just the tool surface.

If you are working on agent UX, code review workflows, or MCP-based developer tooling, this pattern is worth a look.

Hashtags: #MCP #AIAgents #DeveloperTools #CodeReview #GitHubCopilot #ClaudeCode #Codex
