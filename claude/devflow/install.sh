#!/usr/bin/env bash
set -euo pipefail

DEVFLOW_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SKILLS_DIR="$CLAUDE_DIR/skills"
COMMANDS_DIR="$CLAUDE_DIR/commands"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

echo "Installing devflow from $DEVFLOW_DIR"
echo ""

# Check prerequisites
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is required but not found"
    exit 1
fi

# Ensure directories exist
mkdir -p "$COMMANDS_DIR"

# 1. Link skills via Python (cross-platform: symlink with fallback to copy on Windows)
echo "Linking skills..."
python3 "$DEVFLOW_DIR/install_skills.py" "$DEVFLOW_DIR" "$SKILLS_DIR"

# 2. Copy commands (these are small .md files, copy is fine)
echo "Copying commands..."
for cmd_file in "$DEVFLOW_DIR"/commands/*.md; do
    cmd_name=$(basename "$cmd_file")
    cp "$cmd_file" "$COMMANDS_DIR/$cmd_name"
    echo "  OK: $cmd_name"
done

# 3. Register hooks in settings.json
echo "Registering hooks..."
python3 - "$DEVFLOW_DIR" "$SETTINGS_FILE" << 'PYTHON_SCRIPT'
import json
import sys
from pathlib import Path

devflow_dir = sys.argv[1]
settings_path = Path(sys.argv[2])

# Import hook configuration from install_config.py (single source of truth)
sys.path.insert(0, devflow_dir)
from install_config import build_hooks
DEVFLOW_HOOKS = build_hooks(devflow_dir)

# Load existing settings
settings = {}
if settings_path.exists():
    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        print("  WARNING: existing settings.json is invalid, creating new one")

# Merge hooks — don't overwrite existing non-devflow hooks
existing_hooks = settings.get("hooks", {})

def is_devflow_hook(hook_entry):
    """Check if a hook entry belongs to devflow."""
    for h in hook_entry.get("hooks", []):
        cmd = h.get("command", "")
        if "/devflow/hooks/" in cmd or "\\devflow\\hooks\\" in cmd:
            return True
    return False

for event_name, devflow_entries in DEVFLOW_HOOKS.items():
    existing = existing_hooks.get(event_name, [])
    # Remove old devflow hooks for this event
    cleaned = [e for e in existing if not is_devflow_hook(e)]
    # Add new devflow hooks
    cleaned.extend(devflow_entries)
    existing_hooks[event_name] = cleaned

settings["hooks"] = existing_hooks
settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print("  OK: hooks registered in settings.json")
PYTHON_SCRIPT

# 4. Run tests to verify
echo ""
echo "Running tests..."
if python3 -m pytest "$DEVFLOW_DIR/hooks/tests/" -v --tb=short 2>/dev/null; then
    echo ""
    echo "========================================="
    echo "devflow installed successfully!"
    echo "========================================="
    echo ""
    echo "What was installed:"
    echo "  - 10 automatic hooks (quality, TDD, context, compaction, stop guard, pre-push gate, telemetry, spec tracker)"
    echo "  - 5 skills (spec-driven-dev, behavior-contract, wizard, orchestration, model-routing)"
    echo "  - 4 commands (/spec, /sync, /learn, /pause)"
    echo ""
    echo "Optional: copy CLAUDE.md to your global config:"
    echo "  cp $DEVFLOW_DIR/CLAUDE.md ~/.claude/CLAUDE.md"
    echo ""
    echo "Start a new Claude Code session to activate."
else
    echo ""
    echo "WARNING: Some tests failed. devflow was installed but may not work correctly."
    echo "Run: cd $DEVFLOW_DIR && python3 -m pytest hooks/tests/ -v"
fi
