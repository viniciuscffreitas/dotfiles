"""sync_report.py — display project-profile.json after discovery_scan.

Used by /sync to show the current project profile in a human-readable format.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_state_dir


def _get_state_dir() -> Path:
    """Thin wrapper — exists so tests can patch it."""
    return get_state_dir()


def _format_profile(profile: dict) -> str:
    lines = ["[devflow:sync] Project profile"]
    lines.append("-" * 40)

    root = profile.get("project_root")
    if root:
        lines.append(f"  Project root:    {root}")

    if not profile.get("in_project"):
        lines.append("  Status:          not in project")
    else:
        tc = profile.get("toolchain") or "unknown"
        lines.append(f"  Toolchain:       {tc}")
        lines.append(f"  Test framework:  {profile.get('test_framework') or 'unknown'}")
        lines.append(f"  Issue tracker:   {profile.get('issue_tracker') or 'none'}")

        ds = profile.get("design_system")
        if ds:
            lines.append(f"  Design system:   {ds}")

        injected = profile.get("injected_skills") or []
        if injected:
            lines.append(f"  Learned skills:  {', '.join(injected)}")

    return "\n".join(lines)


def main() -> int:
    state_dir = _get_state_dir()
    profile_path = state_dir / "project-profile.json"

    if not profile_path.exists():
        print(
            "[devflow:sync] No profile found — run discovery_scan.py first.\n"
            "  Tip: /sync will re-run the scan automatically."
        )
        return 0

    try:
        profile = json.loads(profile_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[devflow:sync] Could not read profile: {e}", file=sys.stderr)
        return 1

    print(_format_profile(profile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
