#!/usr/bin/env bash
set -euo pipefail

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SOURCE="$SCRIPT_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

SELECTED_TOOLS=()
INSTALL_SCOPE=""
PROJECT_DIR=""
UPDATED_PATHS=()

print_header() {
    echo -e "${BLUE}obo-mcp installer${NC}"
    echo "================="
    echo ""
    echo "This script installs the obo-mcp MCP server from the current checkout:"
    echo "  $REPO_SOURCE"
    echo ""
    echo "It will ask which clients you use, wire obo-mcp into their MCP config,"
    echo "and install the packaged workflow instructions into the right place."
    echo ""
}

detect_vscode_user_dir() {
    case "$(uname -s)" in
        Darwin*) echo "$HOME/Library/Application Support/Code/User" ;;
        Linux*) echo "$HOME/.config/Code/User" ;;
        CYGWIN*|MINGW*|MSYS*) echo "$HOME/AppData/Roaming/Code/User" ;;
        *)
            echo -e "${RED}Unsupported operating system: $(uname -s)${NC}" >&2
            exit 1
            ;;
    esac
}

detect_cline_settings_path() {
    case "$(uname -s)" in
        Darwin*) echo "$HOME/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json" ;;
        Linux*) echo "$HOME/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json" ;;
        CYGWIN*|MINGW*|MSYS*) echo "$HOME/AppData/Roaming/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json" ;;
        *)
            echo -e "${RED}Unsupported operating system: $(uname -s)${NC}" >&2
            exit 1
            ;;
    esac
}

say() {
    echo -e "${BLUE}$1${NC}"
}

warn() {
    echo -e "${YELLOW}$1${NC}"
}

success() {
    echo -e "${GREEN}$1${NC}"
}

require_command() {
    local command_name="$1"
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo -e "${RED}Missing required command: $command_name${NC}" >&2
        exit 1
    fi
}

ensure_dir() {
    local dir_path="$1"
    mkdir -p "$dir_path"
}

record_path() {
    UPDATED_PATHS+=("$1")
}

backup_file() {
    local file_path="$1"
    if [ -f "$file_path" ]; then
        local backup_path="${file_path}.bak.${TIMESTAMP}"
        cp "$file_path" "$backup_path"
        warn "Backed up $file_path to $backup_path"
    fi
}

copy_with_backup() {
    local source_path="$1"
    local target_path="$2"

    ensure_dir "$(dirname "$target_path")"

    if [ -f "$target_path" ] && cmp -s "$source_path" "$target_path"; then
        success "Up to date: $target_path"
        return 0
    fi

    if [ -f "$target_path" ]; then
        backup_file "$target_path"
    fi

    cp "$source_path" "$target_path"
    success "Installed $target_path"
    record_path "$target_path"
}

merge_markdown_block() {
    local source_path="$1"
    local target_path="$2"
    local start_marker="$3"
    local end_marker="$4"
    local temp_output

    ensure_dir "$(dirname "$target_path")"
    temp_output="$(mktemp)"

    python3 - "$source_path" "$target_path" "$start_marker" "$end_marker" > "$temp_output" <<'PY'
from pathlib import Path
import re
import sys

source_path, target_path, start_marker, end_marker = sys.argv[1:5]
source_text = Path(source_path).read_text()
target = Path(target_path)
target_text = target.read_text() if target.exists() else ""
block = f"{start_marker}\n{source_text.rstrip()}\n{end_marker}\n"
pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker) + r"\n?", re.S)

if pattern.search(target_text):
    updated = pattern.sub(block, target_text, count=1)
elif target_text.strip():
    updated = target_text.rstrip() + "\n\n" + block
else:
    updated = block

sys.stdout.write(updated)
PY

    if [ -f "$target_path" ] && cmp -s "$temp_output" "$target_path"; then
        rm -f "$temp_output"
        success "Up to date: $target_path"
        return 0
    fi

    if [ -f "$target_path" ]; then
        backup_file "$target_path"
    fi

    mv "$temp_output" "$target_path"

    success "Merged OBO instructions into $target_path"
    record_path "$target_path"
}

merge_vscode_mcp_server() {
    local target_path="$1"
    local temp_output

    ensure_dir "$(dirname "$target_path")"
    temp_output="$(mktemp)"

    python3 - "$target_path" "$REPO_SOURCE" > "$temp_output" <<'PY'
import json
from pathlib import Path
import sys

target_path = Path(sys.argv[1])
repo_source = sys.argv[2]
if target_path.exists():
    data = json.loads(target_path.read_text())
else:
    data = {}
servers = data.get("servers")
if not isinstance(servers, dict):
    servers = {}
servers["obo-mcp"] = {
    "type": "stdio",
    "command": "uvx",
    "args": ["--from", repo_source, "obo-mcp"],
}
data["servers"] = servers
if "inputs" not in data or not isinstance(data["inputs"], list):
    data["inputs"] = []
sys.stdout.write(json.dumps(data, indent=2) + "\n")
PY

    if [ -f "$target_path" ] && cmp -s "$temp_output" "$target_path"; then
        rm -f "$temp_output"
        success "Up to date: $target_path"
        return 0
    fi

    if [ -f "$target_path" ]; then
        backup_file "$target_path"
    fi

    mv "$temp_output" "$target_path"

    success "Updated VS Code MCP config at $target_path"
    record_path "$target_path"
}

merge_json_mcp_server() {
    local target_path="$1"
    local root_key="$2"
    local temp_output

    ensure_dir "$(dirname "$target_path")"
    temp_output="$(mktemp)"

    python3 - "$target_path" "$root_key" "$REPO_SOURCE" > "$temp_output" <<'PY'
import json
from pathlib import Path
import sys

target_path = Path(sys.argv[1])
root_key = sys.argv[2]
repo_source = sys.argv[3]
if target_path.exists():
    data = json.loads(target_path.read_text())
else:
    data = {}
bucket = data.get(root_key)
if not isinstance(bucket, dict):
    bucket = {}
bucket["obo-mcp"] = {
    "type": "stdio",
    "command": "uvx",
    "args": ["--from", repo_source, "obo-mcp"],
}
data[root_key] = bucket
sys.stdout.write(json.dumps(data, indent=2) + "\n")
PY

    if [ -f "$target_path" ] && cmp -s "$temp_output" "$target_path"; then
        rm -f "$temp_output"
        success "Up to date: $target_path"
        return 0
    fi

    if [ -f "$target_path" ]; then
        backup_file "$target_path"
    fi

    mv "$temp_output" "$target_path"

    success "Updated $target_path"
    record_path "$target_path"
}

merge_codex_config() {
    local target_path="$1"
    local temp_output

    ensure_dir "$(dirname "$target_path")"
    temp_output="$(mktemp)"

    python3 - "$target_path" "$REPO_SOURCE" > "$temp_output" <<'PY'
from pathlib import Path
import re
import sys

target_path = Path(sys.argv[1])
repo_source = sys.argv[2]
block = (
    '[mcp_servers.obo-mcp]\n'
    'command = "uvx"\n'
    f'args = ["--from", "{repo_source}", "obo-mcp"]\n'
)
text = target_path.read_text() if target_path.exists() else ""
pattern = re.compile(r'^\[mcp_servers\.obo-mcp\]\n(?:^(?!\[).*$\n?)*', re.M)

if pattern.search(text):
    updated = pattern.sub(block, text, count=1)
elif text.strip():
    updated = text.rstrip() + "\n\n" + block
else:
    updated = block

sys.stdout.write(updated)
PY

    if [ -f "$target_path" ] && cmp -s "$temp_output" "$target_path"; then
        rm -f "$temp_output"
        success "Up to date: $target_path"
        return 0
    fi

    if [ -f "$target_path" ]; then
        backup_file "$target_path"
    fi

    mv "$temp_output" "$target_path"

    success "Updated Codex MCP config at $target_path"
    record_path "$target_path"
}

has_tool() {
    local requested="$1"
    local tool_name
    for tool_name in "${SELECTED_TOOLS[@]}"; do
        if [ "$tool_name" = "$requested" ]; then
            return 0
        fi
    done
    return 1
}

prompt_tools() {
    local selection
    local token

    echo "Choose the client(s) you want to configure:"
    echo "  1) GitHub Copilot"
    echo "  2) Codex"
    echo "  3) Claude Code"
    echo "  4) Cline"
    echo "  5) All of the above"
    echo ""
    read -r -p "Enter a comma-separated list (for example 1,3 or 5): " selection
    selection="${selection// /}"

    if [ -z "$selection" ] || [ "$selection" = "5" ] || [ "$selection" = "all" ] || [ "$selection" = "ALL" ]; then
        SELECTED_TOOLS=("copilot" "codex" "claude" "cline")
        return
    fi

    IFS=',' read -r -a raw_tokens <<< "$selection"
    for token in "${raw_tokens[@]}"; do
        case "$token" in
            1|copilot|Copilot) SELECTED_TOOLS+=("copilot") ;;
            2|codex|Codex) SELECTED_TOOLS+=("codex") ;;
            3|claude|Claude) SELECTED_TOOLS+=("claude") ;;
            4|cline|Cline) SELECTED_TOOLS+=("cline") ;;
            *)
                echo -e "${RED}Unrecognized selection: $token${NC}" >&2
                exit 1
                ;;
        esac
    done

    if [ "${#SELECTED_TOOLS[@]}" -eq 0 ]; then
        echo -e "${RED}No tools selected.${NC}" >&2
        exit 1
    fi
}

prompt_scope() {
    local selection
    echo ""
    echo "Choose where to install workflow instructions:"
    echo "  1) User-level, when the client supports shared instructions"
    echo "  2) Project-level in a target repository"
    echo ""
    echo "Codex, Claude Code, and Cline still use project files for workflow guidance,"
    echo "so the script will ask for a project directory if you select them."
    echo ""
    read -r -p "Enter 1 or 2 [2]: " selection
    selection="${selection:-2}"

    case "$selection" in
        1) INSTALL_SCOPE="user" ;;
        2) INSTALL_SCOPE="project" ;;
        *)
            echo -e "${RED}Invalid scope selection: $selection${NC}" >&2
            exit 1
            ;;
    esac
}

needs_project_dir() {
    if [ "$INSTALL_SCOPE" = "project" ]; then
        return 0
    fi

    has_tool "codex" && return 0
    has_tool "claude" && return 0
    has_tool "cline" && return 0
    return 1
}

prompt_project_dir() {
    local input_path

    echo ""
    read -r -p "Enter the target project directory for repo-scoped instruction files: " input_path
    if [ -z "$input_path" ]; then
        echo -e "${RED}A project directory is required for this selection.${NC}" >&2
        exit 1
    fi
    if [ ! -d "$input_path" ]; then
        echo -e "${RED}Directory does not exist: $input_path${NC}" >&2
        exit 1
    fi
    PROJECT_DIR="$(cd "$input_path" && pwd)"
}

copilot_instruction_target() {
    local vscode_user_dir
    vscode_user_dir="$(detect_vscode_user_dir)"

    if [ "$INSTALL_SCOPE" = "user" ]; then
        echo "$vscode_user_dir/copilot-instructions.md"
    else
        echo "$PROJECT_DIR/.github/copilot-instructions.md"
    fi
}

copilot_skill_target() {
    local vscode_user_dir
    vscode_user_dir="$(detect_vscode_user_dir)"

    if [ "$INSTALL_SCOPE" = "user" ]; then
        echo "$vscode_user_dir/skills/one-by-one/SKILL.md"
    else
        echo "$PROJECT_DIR/.github/skills/one-by-one/SKILL.md"
    fi
}

copilot_prompt_target() {
    local vscode_user_dir
    vscode_user_dir="$(detect_vscode_user_dir)"

    if [ "$INSTALL_SCOPE" = "user" ]; then
        echo "$vscode_user_dir/prompts/obo.prompt.md"
    else
        echo "$PROJECT_DIR/.github/prompts/obo.prompt.md"
    fi
}

claude_instruction_target() {
    if [ -f "$PROJECT_DIR/.claude/CLAUDE.md" ] || [ -d "$PROJECT_DIR/.claude" ]; then
        echo "$PROJECT_DIR/.claude/CLAUDE.md"
    else
        echo "$PROJECT_DIR/CLAUDE.md"
    fi
}

install_copilot() {
    local vscode_user_dir
    local instruction_target
    local skill_target
    local prompt_target

    say "Installing GitHub Copilot configuration"
    vscode_user_dir="$(detect_vscode_user_dir)"
    merge_vscode_mcp_server "$vscode_user_dir/mcp.json"

    instruction_target="$(copilot_instruction_target)"
    skill_target="$(copilot_skill_target)"
    prompt_target="$(copilot_prompt_target)"

    merge_markdown_block \
        "$SCRIPT_DIR/templates/agent-setup/copilot/copilot-instructions.md" \
        "$instruction_target" \
        "<!-- obo-mcp:start -->" \
        "<!-- obo-mcp:end -->"
    copy_with_backup \
        "$SCRIPT_DIR/templates/agent-setup/copilot/skills/one-by-one/SKILL.md" \
        "$skill_target"
    copy_with_backup \
        "$SCRIPT_DIR/templates/agent-setup/copilot/prompts/obo.prompt.md" \
        "$prompt_target"
    echo ""
}

install_codex() {
    local codex_config="$HOME/.codex/config.toml"
    local agents_target="$PROJECT_DIR/AGENTS.md"

    say "Installing Codex configuration"
    merge_codex_config "$codex_config"
    merge_markdown_block \
        "$SCRIPT_DIR/templates/agent-setup/AGENTS.md" \
        "$agents_target" \
        "<!-- obo-mcp:start -->" \
        "<!-- obo-mcp:end -->"
    echo ""
}

install_claude() {
    local claude_config="$HOME/.claude/settings.json"
    local claude_target

    say "Installing Claude Code configuration"
    merge_json_mcp_server "$claude_config" "mcpServers"
    claude_target="$(claude_instruction_target)"
    merge_markdown_block \
        "$SCRIPT_DIR/templates/agent-setup/CLAUDE.md" \
        "$claude_target" \
        "<!-- obo-mcp:start -->" \
        "<!-- obo-mcp:end -->"
    echo ""
}

install_cline() {
    local cline_config
    local cline_rules_target="$PROJECT_DIR/.clinerules"

    say "Installing Cline configuration"
    cline_config="$(detect_cline_settings_path)"
    merge_json_mcp_server "$cline_config" "mcpServers"
    merge_markdown_block \
        "$SCRIPT_DIR/templates/agent-setup/AGENTS.md" \
        "$cline_rules_target" \
        "<!-- obo-mcp:start -->" \
        "<!-- obo-mcp:end -->"
    echo ""
}

print_plan() {
    echo "Selected clients: ${SELECTED_TOOLS[*]}"
    echo "Instruction scope: $INSTALL_SCOPE"
    if [ -n "$PROJECT_DIR" ]; then
        echo "Project directory: $PROJECT_DIR"
    fi
    echo ""
    echo "The MCP server entries will use this checkout in uvx:"
    echo "  uvx --from $REPO_SOURCE obo-mcp"
    echo ""
}

print_summary() {
    local updated_path

    echo "Installation complete."
    echo ""
    if [ "${#UPDATED_PATHS[@]}" -gt 0 ]; then
        echo "Updated files:"
        for updated_path in "${UPDATED_PATHS[@]}"; do
            echo "  - $updated_path"
        done
        echo ""
    fi

    echo "If you want clients to install obo-mcp from the published GitHub URL instead"
    echo "of this local checkout, use the manual commands in README.md and replace the"
    echo "local --from path with git+https://github.com/warnes-innovations/obo-mcp."
}

main() {
    require_command python3

    print_header
    prompt_tools
    prompt_scope

    if needs_project_dir; then
        prompt_project_dir
    fi

    print_plan

    has_tool "copilot" && install_copilot
    has_tool "codex" && install_codex
    has_tool "claude" && install_claude
    has_tool "cline" && install_cline

    print_summary
}

main "$@"
