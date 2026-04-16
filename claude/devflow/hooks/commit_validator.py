"""commit_validator.py — PreToolUse hook for Conventional Commits validation.

Non-blocking: always exits 0. Prints a warning to stdout when the commit
message does not follow the Conventional Commits spec so Claude can fix it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin


_CONVENTIONAL_RE = re.compile(
    r'^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)'
    r'(\([^)]+\))?(!)?:\s+\S+'
)

# Match -m / --message with single or double quoted value
_MSG_RE = re.compile(r'(?:-m|--message)\s+(["\'])(.*?)\1', re.DOTALL)


def _is_conventional(message: str) -> bool:
    """Return True if the first line of message matches Conventional Commits format."""
    first_line = message.split("\n", 1)[0].strip()
    if first_line.startswith(("Merge ", "Revert ")):
        return True
    return bool(_CONVENTIONAL_RE.match(first_line))


def _extract_message(command: str) -> Optional[str]:
    """Extract commit message from a git commit command, or None if not extractable."""
    if "git commit" not in command:
        return None
    if "--amend" in command or "--no-edit" in command:
        return None

    # Heredoc: extract lines between EOF markers
    if "<<" in command and "EOF" in command:
        lines = command.splitlines()
        in_body = False
        body_lines = []
        for line in lines:
            if "EOF" in line and not in_body:
                in_body = True
                continue
            if in_body and ("EOF" in line or line.strip() == ")\""):
                break
            if in_body:
                body_lines.append(line)
        if body_lines:
            return "\n".join(body_lines).strip()

    m = _MSG_RE.search(command)
    if m:
        return m.group(2).strip()

    return None


def main() -> int:
    hook_data = read_hook_stdin()
    inp = hook_data.get("tool_input", {})
    if not inp:
        return 0

    command = inp.get("command", "")
    message = _extract_message(command)
    if message is None:
        return 0

    if not _is_conventional(message):
        print(
            f"[devflow:commit] WARNING — commit message does not follow Conventional Commits.\n"
            f"  Message: {message[:80]!r}\n"
            f"  Expected format: <type>(<scope>): <description>\n"
            f"  Valid types: feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert\n"
            f"  Example: feat(auth): add OAuth2 support"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
