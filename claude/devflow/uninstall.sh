#!/usr/bin/env bash
set -euo pipefail

DEVFLOW_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SKILLS_DIR="$CLAUDE_DIR/skills"
COMMANDS_DIR="$CLAUDE_DIR/commands"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

echo "Uninstalling devflow..."
echo ""

# 1. Remove skill symlinks (only if they point to devflow)
echo "Removing skills..."
for skill_dir in "$DEVFLOW_DIR"/skills/devflow-*/; do
    skill_name=$(basename "$skill_dir")
    target="$SKILLS_DIR/$skill_name"
    if [ -L "$target" ]; then
        rm "$target"
        echo "  OK: removed $skill_name"
    elif [ -d "$target" ]; then
        echo "  SKIP: $skill_name (not a symlink — may be user-modified)"
    fi
done

# 2. Remove commands
echo "Removing commands..."
for cmd_file in "$DEVFLOW_DIR"/commands/*.md; do
    cmd_name=$(basename "$cmd_file")
    target="$COMMANDS_DIR/$cmd_name"
    if [ -f "$target" ]; then
        rm "$target"
        echo "  OK: removed $cmd_name"
    fi
done

# 3. Remove hooks from settings.json
echo "Removing hooks from settings.json..."
python3 - "$SETTINGS_FILE" << 'PYTHON_SCRIPT'
import json
import sys
from pathlib import Path

settings_path = Path(sys.argv[1])

if not settings_path.exists():
    print("  No settings.json found, nothing to remove")
    sys.exit(0)

try:
    settings = json.loads(settings_path.read_text())
except json.JSONDecodeError:
    print("  WARNING: settings.json is invalid, skipping")
    sys.exit(0)

hooks = settings.get("hooks", {})
changed = False

for event_name in list(hooks.keys()):
    entries = hooks[event_name]
    cleaned = []
    for entry in entries:
        is_devflow = any("/devflow/hooks/" in h.get("command", "") for h in entry.get("hooks", []))
        if not is_devflow:
            cleaned.append(entry)
        else:
            changed = True
    if cleaned:
        hooks[event_name] = cleaned
    else:
        del hooks[event_name]

if changed:
    settings["hooks"] = hooks
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print("  OK: devflow hooks removed from settings.json")
else:
    print("  No devflow hooks found in settings.json")
PYTHON_SCRIPT

echo ""
echo "========================================="
echo "devflow uninstalled."
echo "========================================="
echo ""
echo "The devflow directory ($DEVFLOW_DIR) was NOT deleted."
echo "To fully remove: rm -rf $DEVFLOW_DIR"
