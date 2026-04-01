#!/usr/bin/env python3
"""
CWDChanged hook — detects toolchain when Claude switches working directory.

Injects context about the new project's stack and warns when the toolchain
differs from the previous directory (e.g. Flutter → Node.js), so Claude
attends to the different conventions.

Always exits 0 — never blocks execution.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import ToolchainKind, detect_toolchain, get_state_dir, read_hook_stdin


def _get_state_dir() -> Path:
    return get_state_dir()


def _toolchain_name(kind: ToolchainKind | None) -> str:
    if kind is None:
        return "unknown"
    return kind.name.lower()


def main() -> int:
    try:
        hook_data = read_hook_stdin()
        cwd = hook_data.get("cwd") or ""
        if not cwd:
            return 0

        cwd_path = Path(cwd)
        toolchain_kind, _ = detect_toolchain(cwd_path)
        tc_name = _toolchain_name(toolchain_kind)

        state_dir = _get_state_dir()
        state_file = state_dir / "last_cwd.json"

        # Detect toolchain change
        prev_tc: str | None = None
        if state_file.exists():
            try:
                prev = json.loads(state_file.read_text())
                prev_tc = prev.get("toolchain")
            except (json.JSONDecodeError, OSError):
                pass

        # Persist current state
        try:
            state_file.write_text(json.dumps({"cwd": cwd, "toolchain": tc_name}))
        except OSError:
            pass

        msg = f"[devflow:cwd] Changed to {cwd_path.name} | toolchain={tc_name}"

        tc_changed = prev_tc and prev_tc.lower() != tc_name and tc_name != "unknown"
        if tc_changed:
            msg += f" (switched from {prev_tc} — check project conventions)"

        print(msg)

    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
