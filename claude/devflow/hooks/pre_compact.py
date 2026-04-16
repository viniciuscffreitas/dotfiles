"""PreCompact hook — saves state before auto-compaction.
Captures: session ID, trigger, active spec, working directory, and project profile.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_session_id, get_state_dir, read_hook_stdin


def _find_active_spec() -> dict | None:
    state_dir = get_state_dir()
    active_file = state_dir / "active-spec.json"
    if not active_file.exists():
        return None
    try:
        data = json.loads(active_file.read_text())
        if data.get("status") != "IMPLEMENTING":
            return None
        return {"plan_path": data.get("plan_path", ""), "status": "IMPLEMENTING"}
    except (json.JSONDecodeError, OSError):
        return None


def _load_project_profile() -> dict | None:
    state_dir = get_state_dir()
    profile_path = state_dir / "project-profile.json"
    if profile_path.exists():
        try:
            return json.loads(profile_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def main() -> int:
    try:
        hook_data = read_hook_stdin()
        state_dir = get_state_dir()

        # Save full pre-compact state (used by post_compact_restore)
        state = {
            "session_id": get_session_id(),
            "trigger": hook_data.get("trigger", "auto"),
            "active_spec": _find_active_spec(),
            "cwd": os.getcwd(),
            "project_profile": _load_project_profile(),
        }
        state_file = state_dir / "pre-compact.json"
        try:
            state_file.write_text(json.dumps(state, indent=2))
        except OSError as e:
            print(f"[devflow] ERROR: could not save pre-compact state: {e}", file=sys.stderr)

        # Increment per-session compaction counter (read by task_telemetry at session end)
        count_file = state_dir / "compaction_count.json"
        count = 0
        try:
            if count_file.exists():
                count = json.loads(count_file.read_text()).get("count", 0)
        except (OSError, json.JSONDecodeError):
            count = 0  # corrupt file — start fresh
        try:
            count_file.write_text(json.dumps({"count": count + 1}))
        except OSError:
            pass  # counter loss is non-fatal

        print("[devflow] State saved before compaction", file=sys.stderr)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
