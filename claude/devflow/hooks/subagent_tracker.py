#!/usr/bin/env python3
"""
SubagentStart / SubagentStop hook — tracks Agent tool spawning per session.

Records each spawned subagent with type, description, and timestamp to
~/.claude/devflow/state/$SESSION/subagents.jsonl. Enables cost attribution
and orchestration visibility per delegated agent.

Always exits 0 — never blocks execution.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_state_dir, read_hook_stdin


def _get_state_dir() -> Path:
    return get_state_dir()


def main() -> int:
    try:
        hook_data = read_hook_stdin()
        event = hook_data.get("hook_event_name") or ""
        subagent_type = hook_data.get("subagent_type") or ""
        session_id = hook_data.get("session_id") or ""

        if not event or event not in ("SubagentStart", "SubagentStop"):
            return 0

        record: dict = {
            "event": "start" if event == "SubagentStart" else "stop",
            "ts": time.time(),
            "session_id": session_id,
            "subagent_type": subagent_type,
        }

        if event == "SubagentStart":
            description = hook_data.get("description") or ""
            record["description"] = description
            print(
                f"[devflow:subagent] spawned type={subagent_type or 'unknown'}"
                + (f" — {description[:80]}" if description else "")
            )
        else:
            print(f"[devflow:subagent] finished type={subagent_type or 'unknown'}")

        state_dir = _get_state_dir()
        log_path = state_dir / "subagents.jsonl"
        with log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
