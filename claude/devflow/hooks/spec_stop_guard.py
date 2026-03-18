"""
Stop hook — blocks session exit if an active spec is IMPLEMENTING, PENDING, or in_progress.
Also cleans up the discovery-ran marker so no future session inherits stale state.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_state_dir, hook_block

# Specs older than 24 hours are considered abandoned
SPEC_EXPIRY_SECONDS = 24 * 60 * 60


def _has_active_spec() -> tuple[bool, str]:
    state_dir = get_state_dir()
    active_file = state_dir / "active-spec.json"
    if active_file.exists():
        try:
            data = json.loads(active_file.read_text())
            status = data.get("status", "")
            if status in ("IMPLEMENTING", "PENDING", "in_progress"):
                # Check timestamp — abandon if too old
                started_at = data.get("started_at", 0)
                if started_at and (time.time() - started_at) > SPEC_EXPIRY_SECONDS:
                    return False, ""
                plan_path = data.get("plan_path", "unknown")
                return True, f"{plan_path} ({status})"
        except (json.JSONDecodeError, OSError) as e:
            # Fail-safe: corrupt file should NOT block forever
            # Check file age as fallback
            try:
                file_age = time.time() - active_file.stat().st_mtime
                if file_age > SPEC_EXPIRY_SECONDS:
                    return False, ""
            except OSError:
                pass
            print(f"[devflow] WARNING: could not read active-spec, assuming active: {e}", file=sys.stderr)
            return True, "unknown (corrupt state file)"
    return False, ""


def _cleanup_discovery_marker() -> None:
    state_dir = get_state_dir()
    marker = state_dir / "discovery-ran"
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    active, description = _has_active_spec()
    if active:
        reason = (
            f"[devflow] Active spec detected: {description}\n"
            f"Complete it or use /pause to explicitly pause.\n"
            f"After /pause, session exit will be allowed."
        )
        print(hook_block(reason))

    _cleanup_discovery_marker()
    return 0


if __name__ == "__main__":
    sys.exit(main())
