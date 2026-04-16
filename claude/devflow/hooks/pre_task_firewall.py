"""
PreToolUse hook — context firewall delegator.

Runs before each tool use to decide if the task should be delegated
to a context firewall sub-agent with a clean, minimal context.

Core principle: advisory only. Always exits 0.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

_DEVFLOW_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from _util import get_session_id, get_state_dir, read_hook_stdin, read_oversight_level
from agents.firewall import ContextFirewall, FirewallTask

try:
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]


_READ_ONLY_COMMANDS = frozenset({"grep", "cat", "ls", "find"})


def _is_delegatable(tool_use: dict) -> bool:
    """Returns True if the tool use is a read-only operation safe to delegate."""
    tool_name = tool_use.get("tool_name") or tool_use.get("name", "")
    if tool_name in ("Write", "Edit", "MultiEdit"):
        return False
    if tool_name == "Read":
        return True
    if tool_name == "Bash":
        tool_input = tool_use.get("tool_input") or tool_use.get("input", {})
        cmd = tool_input.get("command", "")
        first_token = cmd.strip().split()[0] if cmd.strip() else ""
        return first_token in _READ_ONLY_COMMANDS
    return False


def run(state_dir: Path, tool_use: dict) -> None:
    state_dir = Path(state_dir)

    # 1. Read oversight_level from risk-profile.json
    oversight_level = read_oversight_level(state_dir, default="standard")

    # 2. Skip on vibe
    if oversight_level == "vibe":
        print("[devflow:firewall] skipped (vibe)")
        return

    # 3. Decide whether to delegate
    delegated = False
    task_id = str(uuid.uuid4())[:8]
    result = None

    if _is_delegatable(tool_use) and oversight_level in ("strict", "human_review"):
        # Build minimal context: active-spec + the file being read (if any)
        allowed_paths: list[str] = []
        spec_path = state_dir / "active-spec.json"
        if spec_path.exists():
            allowed_paths.append(str(spec_path))

        tool_name = tool_use.get("tool_name") or tool_use.get("name", "")
        if tool_name == "Read":
            file_path = (tool_use.get("tool_input") or {}).get("file_path", "")
            if file_path:
                allowed_paths.append(file_path)

        task = FirewallTask(
            task_id=task_id,
            instruction="Provide a brief summary of the content provided.",
            allowed_paths=allowed_paths,
            allowed_tools=["Read"],
        )
        result = ContextFirewall().run(task)
        delegated = True

    # 4. Print result
    print(f"[devflow:firewall] task_id={task_id} delegated={delegated}")

    # 5. Update telemetry
    store_cls = TelemetryStore
    if store_cls is not None and result is not None:
        try:
            store = store_cls()
            store.record({
                "task_id": get_session_id(),
                "firewall_delegated": delegated,
                "firewall_task_id": task_id,
                "firewall_success": result.success,
                "firewall_duration_ms": result.duration_ms,
            })
        except Exception:
            pass


def main() -> int:
    try:
        tool_use = read_hook_stdin()
        run(get_state_dir(), tool_use)
    except Exception as exc:
        print(f"[devflow:firewall] error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
