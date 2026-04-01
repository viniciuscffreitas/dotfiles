#!/usr/bin/env python3
"""
ConfigChange hook — notifies when devflow-relevant config files change.

Fires when settings.json or devflow-config.json is modified. Outputs a
brief message so the next turn's context reflects that hooks/skills/
permissions have been reloaded.

Silent for unrelated file changes. Always exits 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin

# Files that affect devflow behaviour
_WATCHED = frozenset({"settings.json", "devflow-config.json"})


def main() -> int:
    try:
        hook_data = read_hook_stdin()
        file_path = hook_data.get("file") or ""
        if not file_path:
            return 0

        filename = Path(file_path).name
        if filename not in _WATCHED:
            return 0

        print(f"[devflow:config] {filename} changed — hooks and settings reloaded")

    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
