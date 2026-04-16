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
from _util import CONTEXT_WINDOW_TOKENS, get_session_id, get_state_dir, read_hook_stdin


def _get_state_dir() -> Path:
    """Thin wrapper around get_state_dir() — exists so tests can patch it."""
    return get_state_dir()


# SQLite analytics layer — dual-write partner to sessions.jsonl
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]

TELEMETRY_DIR = Path.home() / ".claude" / "devflow" / "telemetry"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


_PRICING_PER_M: dict[str, dict[str, float]] = {
    "claude-opus-4-6":   {"input": 15.0,  "output": 75.0,  "cache_creation": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6": {"input": 3.0,   "output": 15.0,  "cache_creation": 3.75,  "cache_read": 0.30},
    "claude-haiku-4-5":  {"input": 0.80,  "output": 4.00,  "cache_creation": 1.00,  "cache_read": 0.08},
}
_DEFAULT_PRICING = _PRICING_PER_M["claude-sonnet-4-6"]


def _anxiety_ratio(first_action_tokens: int, window_tokens: int) -> float:
    """Return context_tokens_at_first_action / window_tokens, or 0.0 if either is zero."""
    if not window_tokens or not first_action_tokens:
        return 0.0
    return first_action_tokens / window_tokens


def _estimate_usd(usage: dict, model: str) -> float:
    pricing = _PRICING_PER_M.get(model)
    if pricing is None:
        for key, p in _PRICING_PER_M.items():
            if model.startswith(key):
                pricing = p
                break
    if pricing is None:
        pricing = _DEFAULT_PRICING
    return (
        usage.get("input_tokens", 0) * pricing["input"] / 1_000_000
        + usage.get("output_tokens", 0) * pricing["output"] / 1_000_000
        + usage.get("cache_creation_input_tokens", 0) * pricing["cache_creation"] / 1_000_000
        + usage.get("cache_read_input_tokens", 0) * pricing["cache_read"] / 1_000_000
    )


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


def _is_test_file(path: str) -> bool:
    if not _is_source_file(path):
        return False
    p = Path(path)
    stem = p.stem.lower()
    if stem.startswith("test_") or stem.endswith("_test") or stem.endswith("_spec"):
        return True
    parts = {part.lower() for part in p.parts}
    return bool(parts & {"test", "tests", "spec", "specs", "__tests__"})


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
        tool_calls_total: int
        context_tokens_at_first_action: int
        delegation_tokens: int
        delegation_ratio: float
        estimated_usd: float
        test_retry_count: int
        tdd_followthrough_rate: float
    """
    all_phases: list[tuple[str, str, Optional[str], int]] = []
    running = 0
    delegation_tokens = 0  # tokens in turns where Agent tool was invoked
    current_cycle: Optional[dict] = None  # per-cycle inference state
    tool_calls_count = 0
    first_action_tokens: Optional[int] = None  # cumulative tokens at first source Write/Edit

    # Cost and TDD tracking
    usage_totals: dict = {"input_tokens": 0, "output_tokens": 0,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    model_detected = "claude-sonnet-4-6"
    global_test_calls: dict = {}   # tool_id → bool (is_test_command)
    test_retry_count = 0
    first_test_success_seen = False
    has_source_write = False
    has_test_write = False

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

    # Cap at last 5000 lines — avoids O(n) on huge sessions.
    # Phase markers are near the end; earlier lines won't affect inference.
    from collections import deque
    _MAX_LINES = 5000
    _line_buf: deque[str] = deque(maxlen=_MAX_LINES)
    with open(jsonl_path, encoding="utf-8", errors="ignore") as f:
        for _ln in f:
            _line_buf.append(_ln)

    for line in _line_buf:
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
            msg = entry.get("message", {})
            usage = msg.get("usage", {})
            if usage:
                running += _tokens_for(usage)
                for k in usage_totals:
                    usage_totals[k] += usage.get(k, 0)
            detected = msg.get("model", "")
            if detected:
                model_detected = detected

            content_items = msg.get("content", [])
            turn_tokens = _tokens_for(usage) if usage else 0
            has_agent_call = any(
                isinstance(it, dict) and it.get("type") == "tool_use" and it.get("name") == "Agent"
                for it in content_items
            )
            if has_agent_call:
                delegation_tokens += turn_tokens

            for item in content_items:
                if not isinstance(item, dict) or item.get("type") != "tool_use":
                    continue
                name = item.get("name", "")
                inp = item.get("input", {})
                tool_id = item.get("id", "")
                tool_calls_count += 1

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

                # Track first source-file write for context_tokens_at_first_action + TDD signals
                if name in ("Write", "Edit"):
                    fp = inp.get("file_path", "")
                    if _is_source_file(fp):
                        if first_action_tokens is None:
                            first_action_tokens = running
                        if _is_test_file(fp):
                            has_test_write = True
                        else:
                            has_source_write = True

                # Global test call tracking for test_retry_count
                if name == "Bash" and tool_id:
                    cmd = inp.get("command", "")
                    if _is_test_command(cmd):
                        global_test_calls[tool_id] = True

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
            for item in entry.get("message", {}).get("content", []):
                if not isinstance(item, dict) or item.get("type") != "tool_result":
                    continue
                tid = item.get("tool_use_id", "")
                output = _extract_text(item.get("content", ""))

                # Global test retry tracking
                if tid in global_test_calls:
                    global_test_calls.pop(tid)
                    if not first_test_success_seen:
                        if _is_test_success(output):
                            first_test_success_seen = True
                        else:
                            test_retry_count += 1

                # Per-cycle COMPLETED inference
                if current_cycle and tid in current_cycle["pending_test_calls"]:
                    ts_cmd, tok_cmd = current_cycle["pending_test_calls"].pop(tid)
                    if _is_test_success(output):
                        current_cycle["last_successful_test"] = (ts_cmd, tok_cmd)

    _flush(current_cycle)
    all_phases.sort(key=lambda x: x[3])

    delegation_ratio = delegation_tokens / running if running > 0 else 0.0
    tdd_followthrough_rate = 1.0 if not has_source_write else (1.0 if has_test_write else 0.0)

    return {
        "phases": [
            {"ts": ts, "phase": phase, "task_id": task_id, "tokens_cumulative": cum}
            for ts, phase, task_id, cum in all_phases
        ],
        "total_tokens": running,
        "tool_calls_total": tool_calls_count,
        "context_tokens_at_first_action": first_action_tokens or 0,
        "delegation_tokens": delegation_tokens,
        "delegation_ratio": delegation_ratio,
        "estimated_usd": _estimate_usd(usage_totals, model_detected),
        "test_retry_count": test_retry_count,
        "tdd_followthrough_rate": tdd_followthrough_rate,
    }


def _find_session_jsonl(session_id: str, cwd: str) -> Optional[Path]:
    slug = _cwd_to_slug(cwd)
    candidate = PROJECTS_DIR / slug / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None


def main() -> int:
    try:
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
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            pass

        # Read compaction count from session state file (written by pre_compact.py)
        compaction_events = 0
        try:
            count_file = _get_state_dir() / "compaction_count.json"
            if count_file.exists():
                compaction_events = json.loads(count_file.read_text()).get("count", 0)
        except (OSError, json.JSONDecodeError):
            pass

        # Dual-write to SQLite analytics layer
        if TelemetryStore is not None:
            try:
                from datetime import datetime, timezone as tz
                task_desc = None
                for phase in record["phases"]:
                    if phase.get("task_id"):
                        task_desc = phase["task_id"]
                        break

                TelemetryStore().record({
                    "task_id": record["session_id"],
                    "timestamp": datetime.now(tz=tz.utc).isoformat(),
                    "session_id": record["session_id"],
                    "task_description": task_desc,
                    "context_tokens_consumed": record["total_tokens"],
                    "iterations_to_completion": len(record["phases"]),
                    "stack": record["project"],
                    "tool_calls_total": result["tool_calls_total"],
                    "context_tokens_at_first_action": result["context_tokens_at_first_action"],
                    "compaction_events": compaction_events,
                    "estimated_usd": result["estimated_usd"],
                    "test_retry_count": result["test_retry_count"],
                    "tdd_followthrough_rate": result["tdd_followthrough_rate"],
                })
            except Exception as exc:
                print(f"[devflow:telemetry] warning: SQLite write failed: {exc}", file=sys.stderr)

        # Surface context anxiety as tech debt hint when ratio > 50%
        window = hook_data.get("context_window_tokens") or CONTEXT_WINDOW_TOKENS
        ratio = _anxiety_ratio(result["context_tokens_at_first_action"], int(window))
        if ratio > 0.5:
            pct = ratio * 100
            tok = result["context_tokens_at_first_action"]
            print(
                f"[devflow:telemetry] context anxiety detected: {pct:.0f}% of window used before first source write\n"
                f"  session: {session_id}  tokens_at_first_action: {tok:,} / {int(window):,}\n"
                f"  [tech-debt] Consider /compact before heavy source work, or start tasks earlier in session."
            )

    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
