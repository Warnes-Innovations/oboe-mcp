# obo-mcp

MCP server for managing One-By-One (OBO) review sessions.

Provides 9 tools for creating, navigating, and resolving items in priority-scored
session files — replacing raw file-write calls in `/obo` workflows with proper MCP
tool calls.

## Tools

| Tool | Description |
|------|-------------|
| `obo_create` | Create session file + update index.json atomically |
| `obo_list_sessions` | List sessions from index.json |
| `obo_session_status` | Summary stats for a session |
| `obo_next` | Next item: in_progress first, then highest-priority pending |
| `obo_list_items` | All items sorted by priority_score desc |
| `obo_get_item` | Full detail for one item |
| `obo_mark_complete` | Mark item completed with resolution text |
| `obo_mark_skip` | Mark item skipped |
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

## Session Format

Session files live at `{base_dir}/.github/obo_sessions/session_YYYYMMDD_HHMMSS.json`.

Priority score formula: `urgency + importance + (6 - effort) + dependencies`
