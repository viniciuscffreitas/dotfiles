#!/usr/bin/env python3
"""
secrets_gate.py — PreToolUse hook (Write|Edit|MultiEdit)

Scans content being written to disk for hardcoded credentials before
the tool executes. Blocks (exit 2) on real credential patterns.

Never blocks:
  - Test files (path contains /tests/, test_ prefix, conftest)
  - Example/template files (.env.example, .sample, .template)
  - Placeholder values (your-api-key, <YOUR_TOKEN>, etc.)
  - Comment lines
  - env-var references (os.environ, os.getenv, process.env)

Exit codes:
  0 — no credential found (tool proceeds normally)
  2 — credential detected (tool call is blocked)
"""

import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Patterns — ordered by specificity
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("anthropic_key",   re.compile(r'sk-ant-api\d{2}-[A-Za-z0-9_-]{90,}')),
    ("aws_key",         re.compile(r'(?:AKIA|ASIA|AROA|AIDA)[A-Z0-9]{16}')),
    ("github_token",    re.compile(r'gh[pousr]_[A-Za-z0-9_]{36,}')),
    ("private_key_pem", re.compile(r'-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----')),
    ("generic_secret",  re.compile(
        r'(?:secret|password|api_key|access_key|auth_token)\s*(?:=|:)\s*[\'"][^\'"${}()\s]{8,}[\'"]',
        re.IGNORECASE,
    )),
]

# Values that look like placeholders — never block these.
# Applied to the quoted value only (extracted from the match), not the full line.
_PLACEHOLDER_RE = re.compile(
    r'^your[-_]|^<YOUR_|^xxx|^placeholder|^changeme|^dummy',
    re.IGNORECASE,
)

# Quoted value extractor — grabs the content inside first pair of quotes
_QUOTED_VALUE_RE = re.compile(r'["\']([^"\']+)["\']')

# Lines that are definitely environment-variable reads — never block
_ENVREF_RE = re.compile(r'os\.environ|os\.getenv|process\.env|dotenv|getenv\(', re.IGNORECASE)

# Comment prefixes (after stripping whitespace).
# Note: "-- " (SQL) but NOT "--" alone — PEM headers start with "-----BEGIN"
_COMMENT_STARTS = ("#", "//", "-- ", "*", "/*")

# File extensions that are safe by design (examples, docs, templates)
_SAFE_EXTENSIONS = {".example", ".sample", ".template", ".md", ".txt", ".rst"}

# Filename patterns that indicate test/fixture files
_TEST_PATH_RE = re.compile(
    r'(?:/tests?/|/test_|_test\.py$|/conftest\.py$|/spec\.py$|/fixtures?/)',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _is_test_file(file_path: str) -> bool:
    """Return True if the file is a test/fixture file that may have fake creds."""
    path = Path(file_path)
    if path.suffix in _SAFE_EXTENSIONS:
        return True
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
        return True
    if _TEST_PATH_RE.search(file_path):
        return True
    return False


def _is_placeholder(match_text: str) -> bool:
    """Return True if the matched VALUE looks like a placeholder, not a real secret.

    Checks the quoted value inside the match, not the full pattern match, to
    avoid false negatives where a variable name contains words like 'example'.
    """
    # Extract the quoted value from the match (e.g. api_key = "value" → "value")
    qm = _QUOTED_VALUE_RE.search(match_text)
    value = qm.group(1) if qm else match_text
    return bool(_PLACEHOLDER_RE.search(value))


def _scan_line(line: str) -> tuple[str, str] | None:
    """Scan a single line. Return (pattern_name, match_text) or None."""
    stripped = line.strip()
    if not stripped:
        return None
    if any(stripped.startswith(c) for c in _COMMENT_STARTS):
        return None
    if _ENVREF_RE.search(line):
        return None
    for name, pattern in _PATTERNS:
        m = pattern.search(line)
        if m and not _is_placeholder(m.group(0)):
            return name, m.group(0)
    return None


def _scan_text(text: str) -> tuple[str, str] | None:
    """Scan multi-line text. Return first (pattern_name, match_text) found, or None."""
    for line in text.splitlines():
        result = _scan_line(line)
        if result:
            return result
    return None


def _extract_texts(tool_name: str, tool_input: dict) -> list[str]:
    """Extract the text segments to scan from the tool input."""
    if tool_name == "Write":
        return [tool_input.get("content", "")]
    if tool_name == "Edit":
        return [tool_input.get("new_string", "")]
    if tool_name == "MultiEdit":
        return [e.get("new_string", "") for e in tool_input.get("edits", [])]
    return []


def _log_block(file_path: str, pattern_name: str, match_text: str) -> None:
    """Write a one-line entry to the secrets-blocked log and print to stderr."""
    import datetime
    log_dir = Path.home() / ".claude" / "devflow" / "telemetry"
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "file": file_path,
        "pattern": pattern_name,
        "match_prefix": match_text[:20] + "..." if len(match_text) > 20 else match_text,
    }
    with open(log_dir / "secrets_blocked.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Redact most of the match for stderr display
    redacted = match_text[:6] + "***" if len(match_text) > 6 else "***"
    print(
        f"\n[devflow:secrets-gate] BLOCKED — credential detected\n"
        f"  File   : {file_path}\n"
        f"  Pattern: {pattern_name}\n"
        f"  Match  : {redacted}\n"
        f"\n  Replace with an environment variable reference:\n"
        f"    import os; VALUE = os.environ['YOUR_VAR_NAME']\n"
        f"  Never commit secrets. Use .env (gitignored) for local dev.\n",
        file=sys.stderr,
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        # Malformed input — pass through, don't block
        sys.stdout.write(raw if "raw" in dir() else "")
        return 0

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if _is_test_file(file_path):
        sys.stdout.write(raw)
        return 0

    for text in _extract_texts(tool_name, tool_input):
        finding = _scan_text(text)
        if finding:
            pattern_name, match_text = finding
            _log_block(file_path, pattern_name, match_text)
            sys.stdout.write(raw)
            return 2

    sys.stdout.write(raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
