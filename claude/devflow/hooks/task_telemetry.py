"""
Stop hook — scans session JSONL and records per-phase token telemetry.

Detects phase transitions from active-spec.json writes (explicit) and from
natural coding signals (inferred):

  PENDING      : explicit write OR spec_phase_tracker hook
  IMPLEMENTING : explicit write OR first source-file Write/Edit after PENDING
  COMPLETED    : explicit write OR last successful test-runner Bash after IMPLEMENTING

  PENDING → IMPLEMENTING : understand/plan phase
  IMPLEMENTING → COMPLETED: build/verify phase

Output: ~/.claude/devflow/telemetry/sessions.jsonl
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_session_id, read_hook_stdin

TELEMETRY_DIR = Path.home() / ".claude" / "devflow" / "telemetry"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


_SOURCE_EXTS = frozenset({
    ".py", ".dart", ".java", ".kt", ".ts", ".tsx", ".js", ".jsx",
    ".swift", ".go", ".rs", ".rb", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".scala", ".clj", ".ex", ".exs", ".elm", ".vue",
})

_TEST_RUNNER_RE = re.compile(
    r"\bpytest\b|\bflutter\s+test\b|\bmvn\b.*\btest\b|\./mvnw\b.*\btest\b"
    r"|\bdart\s+test\b|\bnpm\s+test\b|\bjest\b|\bgo\s+test\b"
    r"|\bcargo\s+test\b|\brspec\b|\bdotnet\s+test\b|\bmix\s+test\b",
    re.IGNORECASE,
)

_TEST_FAILURE_RE = re.compile(
    r"\d+\s+failed\b|\bFAILED\b|\bFAILURE\b"
    r"|Tests run:.*(?:Failures|Errors):\s*[1-9]"
    r"|[1-9]\d*\s+error",
    re.IGNORECASE,
)

_TEST_SUCCESS_RE = re.compile(
    r"\d+\s+passed\b|All tests passed|BUILD SUCCESS"
    r"|Tests run:.*Failures:\s*0.*Errors:\s*0"
    r"|\d+\s+tests?\s+passed",
    re.IGNORECASE,
)


def _is_source_file(path: str) -> bool:
    return Path(path).suffix.lower() in _SOURCE_EXTS


def _is_test_command(cmd: str) -> bool:
    return bool(_TEST_RUNNER_RE.search(cmd))


def _is_test_success(output: str) -> bool:
    if not output:
        return False
    if _TEST_FAILURE_RE.search(output):
        return False
    return bool(_TEST_SUCCESS_RE.search(output))


def _extract_text(content) -> str:
    """Normalise tool_result content — may be a str or a list of {type, text} blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _cwd_to_slug(cwd: str) -> str:
    return cwd.replace("/", "-")


def _project_name(cwd: str) -> str:
    return Path(cwd).name or cwd


def _tokens_for(usage: dict) -> int:
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("output_tokens", 0)
    )


def _parse_phase_from_write(inp: dict) -> tuple[Optional[str], Optional[str]]:
    """Extract (phase, task_id) from a Write tool_use input targeting active-spec.json."""
    if Path(inp.get("file_path", "")).name != "active-spec.json":
        return None, None
    try:
        spec = json.loads(inp.get("content", "{}"))
        return spec.get("status"), spec.get("plan_path") or spec.get("task_id")
    except (json.JSONDecodeError, TypeError):
        return None, None


def _parse_phase_from_bash(inp: dict) -> Optional[str]:
    """Extract phase from a Bash command that writes active-spec.json."""
    cmd = inp.get("command", "")
    if "active-spec.json" not in cmd:
        return None
    for status in ("PENDING", "IMPLEMENTING", "COMPLETED", "PAUSED"):
        if status in cmd:
            return status
    return None


def parse_session(jsonl_path: Path) -> dict:
    """
    Parse session JSONL and return phase markers with cumulative tokens.

    Explicit phases (writes to active-spec.json) take priority.
    Missing phases are inferred from coding signals per spec cycle:
      - IMPLEMENTING: first Write/Edit to a source file after PENDING
      - COMPLETED: last successful test-runner Bash result after IMPLEMENTING

    Multiple /spec cycles in one session are handled independently — each
    cycle's inference state is flushed before the next PENDING begins.

    Returns:
        phases: list of {ts, phase, task_id, tokens_cumulative}
        total_tokens: int
    """
    all_phases: list[tuple[str, str, Optional[str], int]] = []
    running = 0
    current_cycle: Optional[dict] = None  # per-cycle inference state

    def _new_cycle(task_id: Optional[str]) -> dict:
        return {
            "task_id": task_id,
            "pending_tok": running,
            "has_explicit_impl": False,
            "first_source_write": None,   # (ts, tokens)
            "last_successful_test": None,  # (ts, tokens)
            "pending_test_calls": {},      # tool_id → (ts, tokens)
        }

    def _flush(cycle: Optional[dict]) -> None:
        """Infer missing IMPLEMENTING / COMPLETED for a completed cycle."""
        if not cycle:
            return
        tok0 = cycle["pending_tok"]

        has_impl = any(p[1] == "IMPLEMENTING" and p[3] >= tok0 for p in all_phases)
        if not has_impl and cycle["first_source_write"]:
            ts_i, tok_i = cycle["first_source_write"]
            all_phases.append((ts_i, "IMPLEMENTING", cycle["task_id"], tok_i))

        has_impl_now = any(p[1] == "IMPLEMENTING" and p[3] >= tok0 for p in all_phases)
        has_done = any(p[1] == "COMPLETED" and p[3] >= tok0 for p in all_phases)
        if has_impl_now and not has_done and cycle["last_successful_test"]:
            ts_c, tok_c = cycle["last_successful_test"]
            all_phases.append((ts_c, "COMPLETED", cycle["task_id"], tok_c))

    with open(jsonl_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")

            if entry_type == "assistant":
                ts = entry.get("timestamp", "")
                usage = entry.get("message", {}).get("usage", {})
                if usage:
                    running += _tokens_for(usage)

                for item in entry.get("message", {}).get("content", []):
                    if not isinstance(item, dict) or item.get("type") != "tool_use":
                        continue
                    name = item.get("name", "")
                    inp = item.get("input", {})
                    tool_id = item.get("id", "")

                    # Explicit phase detection
                    if name == "Write":
                        phase, task_id = _parse_phase_from_write(inp)
                        if phase:
                            all_phases.append((ts, phase, task_id, running))
                            if phase == "PENDING":
                                _flush(current_cycle)
                                current_cycle = _new_cycle(task_id)
                            elif phase == "IMPLEMENTING" and current_cycle:
                                current_cycle["has_explicit_impl"] = True
                            continue  # skip source-file check for active-spec.json writes

                    if name == "Bash":
                        phase = _parse_phase_from_bash(inp)
                        if phase:
                            all_phases.append((ts, phase, None, running))
                            if phase == "PENDING":
                                _flush(current_cycle)
                                current_cycle = _new_cycle(None)

                    if not current_cycle:
                        continue

                    # Infer IMPLEMENTING: first source Write/Edit after PENDING
                    if (
                        name in ("Write", "Edit")
                        and not current_cycle["has_explicit_impl"]
                        and current_cycle["first_source_write"] is None
                    ):
                        fp = inp.get("file_path", "")
                        if _is_source_file(fp):
                            current_cycle["first_source_write"] = (ts, running)

                    # Track test runner Bash calls (for COMPLETED inference)
                    in_impl = (
                        current_cycle["has_explicit_impl"]
                        or current_cycle["first_source_write"] is not None
                    )
                    if name == "Bash" and in_impl and tool_id:
                        cmd = inp.get("command", "")
                        if _is_test_command(cmd):
                            current_cycle["pending_test_calls"][tool_id] = (ts, running)

            elif entry_type == "user":
                if not current_cycle:
                    continue
                for item in entry.get("message", {}).get("content", []):
                    if not isinstance(item, dict) or item.get("type") != "tool_result":
                        continue
                    tid = item.get("tool_use_id", "")
                    if tid not in current_cycle["pending_test_calls"]:
                        continue
                    ts_cmd, tok_cmd = current_cycle["pending_test_calls"].pop(tid)
                    output = _extract_text(item.get("content", ""))
                    if _is_test_success(output):
                        current_cycle["last_successful_test"] = (ts_cmd, tok_cmd)

    _flush(current_cycle)
    all_phases.sort(key=lambda x: x[3])

    return {
        "phases": [
            {"ts": ts, "phase": phase, "task_id": task_id, "tokens_cumulative": cum}
            for ts, phase, task_id, cum in all_phases
        ],
        "total_tokens": running,
    }


def _find_session_jsonl(session_id: str, cwd: str) -> Optional[Path]:
    slug = _cwd_to_slug(cwd)
    candidate = PROJECTS_DIR / slug / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None


def main() -> int:
    hook_data = read_hook_stdin()
    session_id = hook_data.get("session_id") or get_session_id()
    cwd = hook_data.get("cwd") or os.getcwd()

    if not session_id or session_id == "default":
        print("[devflow:telemetry] skip: no session_id (hook not invoked by Claude Code)", file=sys.stderr)
        return 0

    jsonl_path = _find_session_jsonl(session_id, cwd)
    if not jsonl_path:
        slug = _cwd_to_slug(cwd)
        print(f"[devflow:telemetry] skip: JSONL not found — {PROJECTS_DIR / slug / f'{session_id}.jsonl'}", file=sys.stderr)
        return 0

    try:
        result = parse_session(jsonl_path)
    except OSError:
        return 0

    if not result["phases"]:
        print(f"[devflow:telemetry] skip: no spec activity detected in {jsonl_path.name}", file=sys.stderr)
        return 0

    record = {
        "session_id": session_id,
        "project": _project_name(cwd),
        "cwd": cwd,
        "ts_end": int(time.time()),
        "phases": result["phases"],
        "total_tokens": result["total_tokens"],
    }

    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    log_path = TELEMETRY_DIR / "sessions.jsonl"
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        existing_ids: set = set()
        corrupt = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    existing_ids.add(parsed.get("session_id"))
                else:
                    corrupt += 1
            except json.JSONDecodeError:
                corrupt += 1
        if corrupt:
            print(f"[devflow:telemetry] warning: {corrupt} corrupt line(s) in {log_path.name}", file=sys.stderr)
        if session_id in existing_ids:
            return 0
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
