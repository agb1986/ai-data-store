#!/usr/bin/env bash
set -e

HOOK_NAME="${1:?usage: uninstall_hook.sh <hook-script-name>}"
HOOK_DEST="$HOME/.claude/hooks/$HOOK_NAME"
SETTINGS="$HOME/.claude/settings.json"

python3 - "$SETTINGS" "$HOOK_DEST" <<'PYEOF'
import json
import sys

settings_path, hook_path = sys.argv[1], sys.argv[2]
command = f"python3 {hook_path}"

try:
    with open(settings_path) as f:
        settings = json.load(f)
except FileNotFoundError:
    print("✓ No settings file, nothing to unregister")
    sys.exit(0)

groups = settings.get("hooks", {}).get("PostToolUse", [])
kept = []
removed = False
for group in groups:
    hooks = [
        h for h in group.get("hooks", [])
        if not (h.get("type") == "command" and h.get("command") == command)
    ]
    if len(hooks) != len(group.get("hooks", [])):
        removed = True
    if hooks:
        kept.append({**group, "hooks": hooks})

if removed:
    settings["hooks"]["PostToolUse"] = kept
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print(f"✓ Unregistered PostToolUse hook from {settings_path}")
else:
    print("✓ Hook was not registered in PostToolUse, nothing to unregister")
PYEOF

if [ -f "$HOOK_DEST" ]; then
    rm "$HOOK_DEST"
    echo "✓ Removed $HOOK_DEST"
fi
