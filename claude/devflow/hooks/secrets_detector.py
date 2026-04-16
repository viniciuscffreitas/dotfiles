"""secrets_detector.py — PreToolUse hook that blocks credential leaks.

Severity levels:
  HIGH   → exit 2 (Claude Code blocks the tool call)
  MEDIUM → exit 0 with warning printed to stdout
"""
from __future__ import annotations

import enum
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin


class Severity(enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"


# ---------------------------------------------------------------------------
# HIGH severity — known credential formats, immediate block
# ---------------------------------------------------------------------------
_HIGH_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'sk-ant-[a-zA-Z0-9_-]{20,}'),      "Anthropic API key"),
    (re.compile(r'sk-[a-zA-Z0-9]{32,}'),            "OpenAI API key"),
    (re.compile(r'gh[prs]_[a-zA-Z0-9]{20,}'),       "GitHub token"),
    (re.compile(r'github_pat_[a-zA-Z0-9_]{10,}'),   "GitHub PAT"),
    (re.compile(r'AKIA[0-9A-Z]{16}'),                "AWS access key"),
    (re.compile(r'ASIA[0-9A-Z]{16}'),                "AWS STS key"),
    (re.compile(r'-----BEGIN [A-Z ]+ PRIVATE KEY-----'), "Private key"),
]

# ---------------------------------------------------------------------------
# MEDIUM severity — credential-like variable assignments with real-looking values
# ---------------------------------------------------------------------------
_MEDIUM_RE = re.compile(
    r'(?i)\b[\w]*(?:password|secret|token|apikey|api_key|passwd|pwd)[\w]*'
    r'\s*[=:]\s*["\'][^"\']{6,}["\']'
)

# Values that look like placeholders/examples — skip MEDIUM detection
_PLACEHOLDER_RE = re.compile(
    r'(?i)(example|placeholder|your_|_here|changeme|insert|replace|fake|dummy|sample)'
)

# File path patterns to skip entirely (example/template files)
_SKIP_SUFFIXES = {".example", ".sample", ".template"}


def _classify(content: str) -> tuple[Optional[Severity], str]:
    """Scan content string and return (severity, description) or (None, '') if clean."""
    for pattern, label in _HIGH_PATTERNS:
        if pattern.search(content):
            return Severity.HIGH, label

    for match in _MEDIUM_RE.finditer(content):
        raw = match.group(0)
        # Extract value: take everything after first '=' or ':'
        after_eq = raw.split("=", 1)[-1] if "=" in raw else raw.split(":", 1)[-1]
        val = after_eq.strip().strip("\"'")
        if not _PLACEHOLDER_RE.search(val):
            return Severity.MEDIUM, f"credential in variable assignment"

    return None, ""


def _extract_content(tool: str, inp: dict) -> list[str]:
    """Return text chunks to scan from a tool input dict."""
    if tool == "Write":
        c = inp.get("content", "")
        return [c] if c else []
    if tool == "Edit":
        n = inp.get("new_string", "")
        return [n] if n else []
    if tool == "MultiEdit":
        return [e.get("new_string", "") for e in inp.get("edits", []) if e.get("new_string")]
    return []


def _should_skip_path(file_path: str) -> bool:
    suffix = Path(file_path).suffix.lower()
    name = Path(file_path).name.lower()
    return (
        suffix in _SKIP_SUFFIXES
        or name.endswith(".example")
        or ".env.example" in file_path.lower()
    )


def main() -> int:
    hook_data = read_hook_stdin()
    tool = hook_data.get("tool", "")
    inp = hook_data.get("tool_input", {})
    if not inp:
        return 0

    file_path = inp.get("file_path", "")
    if file_path and _should_skip_path(file_path):
        return 0

    texts = _extract_content(tool, inp)
    worst: Optional[tuple[Severity, str]] = None

    for text in texts:
        sev, desc = _classify(text)
        if sev == Severity.HIGH:
            worst = (sev, desc)
            break
        if sev == Severity.MEDIUM and worst is None:
            worst = (sev, desc)

    if worst is None:
        return 0

    sev, desc = worst
    if sev == Severity.HIGH:
        print(
            f"[devflow:secrets] BLOCKED — potential credential detected: {desc}\n"
            f"  File: {file_path}\n"
            f"  Remove the secret before writing. Use environment variables or a secrets manager."
        )
        return 2

    print(
        f"[devflow:secrets] WARNING — possible credential detected: {desc}\n"
        f"  File: {file_path}\n"
        f"  Verify this is not a real credential before committing."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
