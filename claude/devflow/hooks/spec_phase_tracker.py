"""
UserPromptSubmit hook — detects /spec in user message and writes PENDING state.

Deterministic: runs before Claude responds, based on user input only.
No LLM instruction-following required for the PENDING transition.

Feeds: task_telemetry (token cost per phase) and spec_stop_guard (exit protection).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_session_id, read_hook_stdin

STATE_ROOT = Path.home() / ".claude" / "devflow" / "state"

_SPEC_RE = re.compile(r"/spec\s*(.*)", re.IGNORECASE)


def _extract_spec_description(prompt: str) -> str:
    match = _SPEC_RE.search(prompt.strip())
    if not match:
        return "unnamed spec"
    desc = match.group(1).strip().strip('"').strip("'")
    return desc or "unnamed spec"


def _write_pending(session_id: str, description: str, *, state_root: Path = STATE_ROOT) -> None:
    state_dir = state_root / session_id
    state_dir.mkdir(parents=True, exist_ok=True)
    spec = {
        "status": "PENDING",
        "plan_path": description,
        "started_at": int(time.time()),
    }
    (state_dir / "active-spec.json").write_text(json.dumps(spec))


def main() -> int:
    try:
        hook_data = read_hook_stdin()
        prompt = hook_data.get("prompt", "")

        if "/spec" not in prompt:
            return 0

        session_id = hook_data.get("session_id") or get_session_id()
        description = _extract_spec_description(prompt)
        _write_pending(session_id, description, state_root=STATE_ROOT)
        print(f"[devflow:spec] PENDING — {description!r}", file=sys.stderr)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
