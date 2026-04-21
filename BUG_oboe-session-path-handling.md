# OBO Session Tool Path Handling Bug: Duplicated `.github/obo_sessions` Segment

## Summary

When calling OBO session tools (e.g., `obo_list_items`) with `base_dir` set to the full `.github/obo_sessions` directory and `session_file` as a bare filename, the tool constructs an invalid path with a duplicated `.github/obo_sessions` segment.

## Steps to Reproduce

**Given:**
- `base_dir = /Users/warnes/src/cv-builder/.github/obo_sessions`
- `session_file = session_20260420_ui-gap-review.json`

**Call:**
```python
obo_list_items(
    base_dir="/Users/warnes/src/cv-builder/.github/obo_sessions",
    session_file="session_20260420_ui-gap-review.json"
)
```

**Result:**
```
/Users/warnes/src/cv-builder/.github/obo_sessions/.github/obo_sessions/session_20260420_ui-gap-review.json
```

**Expected:**
```
/Users/warnes/src/cv-builder/.github/obo_sessions/session_20260420_ui-gap-review.json
```

## Correct Usage

- Pass `base_dir` as the project root (e.g., `/Users/warnes/src/cv-builder`)
- Pass `session_file` as the bare filename (e.g., `session_20260420_ui-gap-review.json`)

**Correct call:**
```python
obo_list_items(
    base_dir="/Users/warnes/src/cv-builder",
    session_file="session_20260420_ui-gap-review.json"
)
```

## Impact
- All OBO session tools that accept `base_dir` and `session_file` are affected.
- Results in file-not-found errors and inability to access session files.

## Proposed Fix
- Add validation to detect if `base_dir` is already `.github/obo_sessions` and avoid appending it again.
- Improve error message to clarify correct usage.

---

**Discovered:** 2026-04-20
**Tested on:** macOS, local workspace
**Related code:** `oboe_mcp.session.resolve_session_file`, `oboe_mcp.server._resolve`
