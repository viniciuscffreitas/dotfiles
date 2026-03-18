"""Shared utilities for devflow hooks."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# Default file length thresholds — overridable via devflow-config.json
FILE_LINES_WARN = 400
FILE_LINES_CRITICAL = 600

DEVFLOW_CONFIG_GLOBAL = Path.home() / ".claude" / "devflow" / "devflow-config.json"

# Context thresholds — compaction fires at (WINDOW - BUFFER), so effective limit is ~167k tokens
CONTEXT_WINDOW_TOKENS = 200_000
AUTOCOMPACT_BUFFER_TOKENS = 33_000
CONTEXT_WARN_PCT = 80.0
CONTEXT_CAUTION_PCT = 90.0

# Shared constants across hooks
GENERATED_PATTERNS = frozenset({
    ".g.dart", ".freezed.dart",
    ".generated.ts", ".generated.js",
    ".pb.go", ".pb.ts", ".pb.py",
    ".moc.cpp",
    ".designer.cs",
})
SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".dart_tool",
    "build", "dist", "migrations",
})


class ToolchainKind(Enum):
    NODEJS = auto()
    FLUTTER = auto()
    MAVEN = auto()
    RUST = auto()
    GO = auto()


_TOOLCHAIN_FINGERPRINTS: list[tuple[str, ToolchainKind]] = [
    ("package.json", ToolchainKind.NODEJS),
    ("pubspec.yaml", ToolchainKind.FLUTTER),
    ("pom.xml", ToolchainKind.MAVEN),
    ("mvnw", ToolchainKind.MAVEN),
    ("Cargo.toml", ToolchainKind.RUST),
    ("go.mod", ToolchainKind.GO),
]

TOOLCHAIN_FINGERPRINT_MAP: dict[ToolchainKind, str] = {
    ToolchainKind.NODEJS: "package.json",
    ToolchainKind.FLUTTER: "pubspec.yaml",
    ToolchainKind.GO: "go.mod",
    ToolchainKind.RUST: "Cargo.toml",
    ToolchainKind.MAVEN: "pom.xml",
}


def detect_toolchain(start_dir: Path, max_levels: int = 4) -> tuple[Optional[ToolchainKind], Optional[Path]]:
    """Detect toolchain kind and project root by walking up directories."""
    current = start_dir
    for _ in range(max_levels):
        for filename, kind in _TOOLCHAIN_FINGERPRINTS:
            if (current / filename).exists():
                return kind, current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None, None


def check_file_length(
    file_path: Path,
    warn: int = FILE_LINES_WARN,
    critical: int = FILE_LINES_CRITICAL,
) -> tuple[bool, bool, int]:
    """Returns (warn, critical, line_count). Limits are configurable."""
    try:
        lines = len(file_path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return False, False, 0
    return lines > warn, lines > critical, lines


def read_hook_stdin() -> dict:
    try:
        content = sys.stdin.read()
        if content.strip():
            return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"[devflow] WARNING: invalid JSON on stdin: {e}", file=sys.stderr)
    except OSError as e:
        print(f"[devflow] WARNING: stdin read error: {e}", file=sys.stderr)
    return {}


def get_edited_file(hook_data: dict) -> Optional[Path]:
    file_path = hook_data.get("tool_input", {}).get("file_path")
    if file_path:
        return Path(file_path)
    return None


def get_bash_command(hook_data: dict) -> Optional[str]:
    cmd = hook_data.get("tool_input", {}).get("command")
    if cmd and cmd.strip():
        return cmd
    return None


def get_session_id() -> str:
    return os.environ.get("CLAUDE_SESSION_ID", "default")


def get_state_dir() -> Path:
    state_dir = Path.home() / ".claude" / "devflow" / "state" / get_session_id()
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def run_command(cmd: list[str], cwd: Optional[Path] = None, timeout: int = 30) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, f"timeout after {timeout}s"
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except OSError as e:
        return 1, f"{type(e).__name__}: {e}"


def hook_context(context: str, event_name: str = "PostToolUse") -> str:
    """Format context output for hook system. Parameterized event name."""
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        }
    })


def hook_block(reason: str) -> str:
    return json.dumps({"decision": "block", "reason": reason})


def hook_deny(reason: str) -> str:
    return json.dumps({"permissionDecision": "deny", "reason": reason})


def load_devflow_config(project_root: Optional[Path] = None) -> dict:
    """Load devflow config with project-level override.

    Resolution order: defaults -> global -> project (.devflow-config.json).
    """
    defaults = {
        "file_length_warn": FILE_LINES_WARN,
        "file_length_critical": FILE_LINES_CRITICAL,
        "learned_skills_auto_inject": True,
        "issue_tracker_override": None,
    }
    config = dict(defaults)

    if DEVFLOW_CONFIG_GLOBAL.exists():
        try:
            config.update(json.loads(DEVFLOW_CONFIG_GLOBAL.read_text()))
        except (json.JSONDecodeError, OSError):
            pass

    if project_root:
        project_config = project_root / ".devflow-config.json"
        if project_config.exists():
            try:
                config.update(json.loads(project_config.read_text()))
            except (json.JSONDecodeError, OSError):
                pass

    return config
