#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_NAME="${1:-log_artifact_entry.py}"
HOOK_SRC="$REPO_ROOT/hooks/$HOOK_NAME"
HOOK_DEST_DIR="$HOME/.claude/hooks"
HOOK_DEST="$HOOK_DEST_DIR/$HOOK_NAME"
SETTINGS="$HOME/.claude/settings.json"

if [ ! -f "$HOOK_SRC" ]; then
    echo "Error: no hook named '$HOOK_NAME' in $REPO_ROOT/hooks/" >&2
    echo "Available hooks:" >&2
    ls "$REPO_ROOT/hooks" >&2
    exit 1
fi

mkdir -p "$HOOK_DEST_DIR"
cp "$HOOK_SRC" "$HOOK_DEST"
chmod +x "$HOOK_DEST"
echo "✓ Installed $HOOK_NAME to $HOOK_DEST"

python3 - "$SETTINGS" "$HOOK_DEST" <<'PYEOF'
import json
import sys

settings_path, hook_path = sys.argv[1], sys.argv[2]
command = f"python3 {hook_path}"

try:
    with open(settings_path) as f:
        settings = json.load(f)
except FileNotFoundError:
    settings = {}

hooks = settings.setdefault("hooks", {})
post_tool_use = hooks.setdefault("PostToolUse", [])

already_installed = any(
    h.get("type") == "command" and h.get("command") == command
    for group in post_tool_use
    for h in group.get("hooks", [])
)

if already_installed:
    print("✓ Hook already registered in PostToolUse, nothing to do")
else:
    post_tool_use.append({"hooks": [{"type": "command", "command": command, "timeout": 8}]})
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print(f"✓ Registered PostToolUse hook in {settings_path}")
PYEOF

echo ""
if ! python3 -c "
import json, sys
cfg = json.load(open('$HOME/.claude.json'))
sys.exit(0 if 'ai-data-store' in cfg.get('mcpServers', {}) else 1)
" 2>/dev/null; then
    echo "⚠ No 'ai-data-store' MCP server found in ~/.claude.json — the hook needs this"
    echo "  to know where to send entries. See the 'Laptop setup' section of the"
    echo "  ai-data-store README to configure it."
fi

echo ""
echo "If this is the first hook registered under ~/.claude/, open /hooks once (or"
echo "restart Claude Code) so the new PostToolUse hook takes effect."
