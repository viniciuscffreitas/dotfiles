"""SessionStart(compact) hook — restores context after compaction.
Reads state saved by pre_compact.py and injects into context via stdout.
Includes project profile for immediate continuity.
Output protocol: plain text lines to stdout (SessionStart hooks use text, not JSON).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_state_dir


def main() -> int:
    state_dir = get_state_dir()
    state_file = state_dir / "pre-compact.json"

    if not state_file.exists():
        return 0

    try:
        state = json.loads(state_file.read_text())
    except json.JSONDecodeError as e:
        print(f"[devflow] WARNING: corrupt pre-compact state, cannot restore: {e}", file=sys.stderr)
        return 0
    except OSError as e:
        print(f"[devflow] WARNING: cannot read pre-compact state: {e}", file=sys.stderr)
        return 0

    lines = ["[devflow Context Restored After Compaction]"]

    active_spec = state.get("active_spec")
    if active_spec:
        plan_path = active_spec.get("plan_path", "Unknown")
        status = active_spec.get("status", "Unknown")
        lines.append(f"Active Spec: {plan_path} (Status: {status})")
        lines.append("Resume from where you left off using the plan above.")
    else:
        lines.append("No active spec was in progress.")

    cwd = state.get("cwd")
    if cwd:
        lines.append(f"Working directory: {cwd}")

    # Only emit profile if discovery_scan hasn't already run in this session
    discovery_marker = state_dir / "discovery-ran"
    profile = state.get("project_profile")
    if profile and not discovery_marker.exists():
        lines.append(f"ISSUE_TRACKER_TYPE={profile.get('issue_tracker', 'none')}")
        ds = profile.get("design_system")
        if ds:
            lines.append(f"DESIGN_SYSTEM_ROOT={ds}")
        lines.append(f"TEST_FRAMEWORK={profile.get('test_framework', 'unknown')}")
        lines.append(f"TOOLCHAIN={profile.get('toolchain', 'unknown')}")
        injected = profile.get("injected_skills", [])
        lines.append(f"LEARNED_SKILLS={','.join(injected) if injected else 'none'}")

    try:
        state_file.unlink()
    except OSError as e:
        print(f"[devflow] WARNING: could not remove state file {state_file}: {e}", file=sys.stderr)

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
