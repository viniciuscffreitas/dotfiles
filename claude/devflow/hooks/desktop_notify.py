#!/usr/bin/env python3
"""
desktop_notify.py — Stop hook (async)

Sends a macOS desktop notification when Claude finishes a response.
Reads the last assistant message from the session transcript (if available)
and uses it as the notification subtitle.

Exit codes:
  0 — always (non-blocking, best-effort)
"""

import json
import subprocess
import sys


_SUBTITLE_MAX = 60


def _read_input() -> dict:
    try:
        return json.loads(sys.stdin.read())
    except Exception:
        return {}


def _last_assistant_text(transcript_path: str) -> str:
    """Return the last assistant message text (truncated), or empty string."""
    try:
        lines = open(transcript_path).readlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("role") != "assistant":
                continue
            content = entry.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            return text[:_SUBTITLE_MAX] + ("…" if len(text) > _SUBTITLE_MAX else "")
            if isinstance(content, str) and content.strip():
                text = content.strip()
                return text[:_SUBTITLE_MAX] + ("…" if len(text) > _SUBTITLE_MAX else "")
    except Exception:
        pass
    return ""


def _notify(title: str, subtitle: str) -> None:
    subtitle_escaped = subtitle.replace('"', '\\"').replace("\\", "\\\\")
    script = f'display notification "{subtitle_escaped}" with title "{title}"'
    subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        timeout=5,
    )


def main() -> int:
    data = _read_input()
    transcript_path = data.get("transcript_path", "")
    subtitle = _last_assistant_text(transcript_path) if transcript_path else ""
    _notify("Claude", subtitle or "Resposta pronta")
    sys.stdout.write(json.dumps(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
