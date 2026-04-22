#!/usr/bin/env bash
# migrate-to-oboe.sh — migrate a project from obo_ tool names to oboe_ (v0.3.0+)
#
# Usage:
#   bash inst/migrate-to-oboe.sh [PROJECT_ROOT]
#
# PROJECT_ROOT defaults to the current working directory.
#
# What this script does:
#   1. Renames .github/obo_sessions/ → .github/oboe_sessions/ and leaves a
#      symlink obo_sessions → oboe_sessions for backward compatibility.
#   2. Updates all agent instruction files that reference old obo_ tool names
#      or obo_sessions paths, including:
#        .github/copilot-instructions.md
#        .github/CLAUDE.md
#        .github/AGENTS.md
#        .github/prompts/*.md  (and *.prompt.md anywhere under .github/)
#        Any SKILL.md found under the project root
#   3. Prints a summary of every change made.
#
# The script is idempotent: running it twice on the same project is safe.

set -euo pipefail

ROOT="${1:-.}"
ROOT="$(cd "$ROOT" && pwd)"
GITHUB="$ROOT/.github"
CHANGED=0

info()    { echo "  $*"; }
changed() { echo "  ✓ $*"; CHANGED=$((CHANGED + 1)); }
skipped() { echo "  — $*"; }

echo ""
echo "=== oboe-mcp migration: obo_ → oboe_ ==="
echo "    Project root: $ROOT"
echo ""

# ---------------------------------------------------------------------------
# 1. Session directory
# ---------------------------------------------------------------------------
echo "[ Session directory ]"

OLD_DIR="$GITHUB/obo_sessions"
NEW_DIR="$GITHUB/oboe_sessions"

if [[ -d "$NEW_DIR" && ! -L "$NEW_DIR" ]]; then
    skipped ".github/oboe_sessions/ already exists"
elif [[ -d "$OLD_DIR" && ! -L "$OLD_DIR" ]]; then
    mv "$OLD_DIR" "$NEW_DIR"
    changed "Renamed .github/obo_sessions/ → .github/oboe_sessions/"
else
    skipped ".github/obo_sessions/ not found (nothing to rename)"
fi

if [[ -L "$OLD_DIR" ]]; then
    skipped "Symlink .github/obo_sessions → oboe_sessions already exists"
elif [[ -d "$NEW_DIR" ]]; then
    ln -s oboe_sessions "$OLD_DIR"
    changed "Created symlink .github/obo_sessions → oboe_sessions"
fi

# ---------------------------------------------------------------------------
# 2. Collect agent instruction files to update
# ---------------------------------------------------------------------------
echo ""
echo "[ Agent instruction files ]"

# Explicit well-known locations
CANDIDATE_FILES=(
    "$GITHUB/copilot-instructions.md"
    "$GITHUB/CLAUDE.md"
    "$GITHUB/AGENTS.md"
)

# Prompts under .github/
while IFS= read -r f; do
    CANDIDATE_FILES+=("$f")
done < <(find "$GITHUB" -type f \( -name "*.prompt.md" -o -name "*.md" \) \
         -path "*/prompts/*" 2>/dev/null)

# SKILL.md files anywhere under project root (excluding .git and node_modules)
while IFS= read -r f; do
    CANDIDATE_FILES+=("$f")
done < <(find "$ROOT" -name "SKILL.md" \
         -not -path "*/.git/*" \
         -not -path "*/node_modules/*" \
         -not -path "*/renv/*" 2>/dev/null)

# ---------------------------------------------------------------------------
# 3. Apply substitutions to each file
# ---------------------------------------------------------------------------
update_file() {
    local f="$1"
    [[ -f "$f" ]] || return 0

    local before
    before="$(md5sum "$f" 2>/dev/null | awk '{print $1}')"

    # obo_ tool name prefix → oboe_  (word-boundary aware)
    sed -i "s/\bobo_\([a-zA-Z]\)/oboe_\1/g" "$f"
    # obo_sessions path → oboe_sessions
    sed -i 's/obo_sessions/oboe_sessions/g' "$f"

    local after
    after="$(md5sum "$f" 2>/dev/null | awk '{print $1}')"

    if [[ "$before" != "$after" ]]; then
        changed "${f#"$ROOT/"}"
    else
        skipped "${f#"$ROOT/"} (no changes needed)"
    fi
}

# Deduplicate
declare -A SEEN
for f in "${CANDIDATE_FILES[@]}"; do
    [[ -z "$f" ]] && continue
    [[ -n "${SEEN[$f]+x}" ]] && continue
    SEEN[$f]=1
    update_file "$f"
done

# ---------------------------------------------------------------------------
# 4. Summary
# ---------------------------------------------------------------------------
echo ""
if [[ $CHANGED -gt 0 ]]; then
    echo "=== Migration complete: $CHANGED change(s) applied. ==="
else
    echo "=== Migration complete: nothing to change (already up to date). ==="
fi
echo ""
