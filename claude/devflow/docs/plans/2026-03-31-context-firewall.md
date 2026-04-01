# Context Firewall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a context firewall pattern to devflow so the main agent can delegate isolated read-only tasks to a clean-context sub-agent spawned via `claude -p`.

**Architecture:** A `ContextFirewall` class in `agents/firewall.py` wraps `subprocess.run(["claude", "-p", ...])` with timeout enforcement and never raises. A `pre_task_firewall.py` PreToolUse hook reads the risk profile and delegates eligible read-only tool uses when oversight is strict/human_review. Four new columns are migrated into the TelemetryStore via ALTER TABLE.

**Tech Stack:** Python 3.11+, subprocess, dataclasses, sqlite3, pytest, unittest.mock

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `agents/__init__.py` | Package marker (empty) |
| Create | `agents/firewall.py` | `FirewallTask`, `FirewallResult` dataclasses + `ContextFirewall` class |
| Create | `hooks/pre_task_firewall.py` | PreToolUse hook + `_is_delegatable()` |
| Modify | `telemetry/store.py` | Add 4 firewall columns to `_COLUMNS`, `_CREATE_TABLE`, and `_init_schema` |
| Create | `hooks/tests/test_firewall.py` | All firewall tests |

---

## Task 1: FirewallTask + FirewallResult dataclasses

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/firewall.py` (dataclasses only)
- Create: `hooks/tests/test_firewall.py` (dataclass tests only)

- [ ] **Step 1.1: Write the failing tests**

Create `hooks/tests/test_firewall.py`:

```python
"""Tests for ContextFirewall and pre_task_firewall hook."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.firewall import ContextFirewall, FirewallResult, FirewallTask


# ---------------------------------------------------------------------------
# FirewallTask
# ---------------------------------------------------------------------------

class TestFirewallTask:
    def test_instantiates_with_required_fields(self):
        task = FirewallTask(
            task_id="t1",
            instruction="summarize this file",
            allowed_paths=["/tmp/foo.py"],
            allowed_tools=["Read"],
        )
        assert task.task_id == "t1"
        assert task.instruction == "summarize this file"
        assert task.allowed_paths == ["/tmp/foo.py"]
        assert task.allowed_tools == ["Read"]

    def test_timeout_seconds_defaults_to_120(self):
        task = FirewallTask(
            task_id="t2",
            instruction="analyze",
            allowed_paths=[],
            allowed_tools=[],
        )
        assert task.timeout_seconds == 120

    def test_context_budget_defaults_to_4000(self):
        task = FirewallTask(
            task_id="t3",
            instruction="analyze",
            allowed_paths=[],
            allowed_tools=[],
        )
        assert task.context_budget == 4000


# ---------------------------------------------------------------------------
# FirewallResult
# ---------------------------------------------------------------------------

class TestFirewallResult:
    def test_instantiates_with_all_fields(self):
        r = FirewallResult(
            task_id="r1",
            success=True,
            output="some output",
            tokens_used=None,
            duration_ms=42.5,
            exit_code=0,
            error=None,
        )
        assert r.task_id == "r1"
        assert r.success is True
        assert r.output == "some output"
        assert r.tokens_used is None
        assert r.duration_ms == pytest.approx(42.5)
        assert r.exit_code == 0
        assert r.error is None
```

- [ ] **Step 1.2: Run tests — expect FAIL**

```bash
cd /Users/vini/.claude/devflow
pytest hooks/tests/test_firewall.py::TestFirewallTask hooks/tests/test_firewall.py::TestFirewallResult -v
```

Expected: `ImportError: cannot import name 'FirewallTask'`

- [ ] **Step 1.3: Create `agents/__init__.py`**

Create `agents/__init__.py` with empty content (just a comment):

```python
```

(Empty file — package marker only.)

- [ ] **Step 1.4: Create `agents/firewall.py` with dataclasses only**

```python
"""
ContextFirewall — spawns isolated sub-agents via `claude -p`.

A sub-agent is a context firewall, not a specialist. Each sub-agent
receives a clean context window with only the files it needs.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FirewallTask:
    task_id: str
    instruction: str           # what the sub-agent must do
    allowed_paths: list[str]   # file paths the sub-agent may read
    allowed_tools: list[str]   # tool names the sub-agent may use
    timeout_seconds: int = 120
    context_budget: int = 4000  # max tokens to pass (approx: chars / 4)


@dataclass
class FirewallResult:
    task_id: str
    success: bool
    output: str                # sub-agent stdout
    tokens_used: int | None    # not available from subprocess
    duration_ms: float
    exit_code: int
    error: str | None          # populated if success=False
```

- [ ] **Step 1.5: Run tests — expect PASS**

```bash
pytest hooks/tests/test_firewall.py::TestFirewallTask hooks/tests/test_firewall.py::TestFirewallResult -v
```

Expected: `6 passed`

- [ ] **Step 1.6: Commit**

```bash
git -C /Users/vini/.claude/devflow add agents/__init__.py agents/firewall.py hooks/tests/test_firewall.py
git -C /Users/vini/.claude/devflow commit -m "feat(firewall): add FirewallTask and FirewallResult dataclasses"
```

---

## Task 2: ContextFirewall class

**Files:**
- Modify: `agents/firewall.py` (add ContextFirewall)
- Modify: `hooks/tests/test_firewall.py` (add ContextFirewall tests)

- [ ] **Step 2.1: Add ContextFirewall tests to test_firewall.py**

Append to `hooks/tests/test_firewall.py`:

```python

# ---------------------------------------------------------------------------
# ContextFirewall._build_context
# ---------------------------------------------------------------------------

class TestBuildContext:
    def setup_method(self):
        self.fw = ContextFirewall()

    def test_reads_file_and_includes_header(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("def bar(): pass")
        task = FirewallTask(
            task_id="t1", instruction="analyze",
            allowed_paths=[str(f)], allowed_tools=[],
        )
        ctx = self.fw._build_context(task)
        assert f"=== {f} ===" in ctx
        assert "def bar(): pass" in ctx

    def test_truncates_to_context_budget(self, tmp_path):
        f = tmp_path / "big.py"
        f.write_text("x" * 10_000)
        task = FirewallTask(
            task_id="t2", instruction="analyze",
            allowed_paths=[str(f)], allowed_tools=[],
            context_budget=10,  # 10 tokens = 40 chars budget
        )
        ctx = self.fw._build_context(task)
        assert len(ctx) <= 40

    def test_skips_missing_files(self):
        task = FirewallTask(
            task_id="t3", instruction="analyze",
            allowed_paths=["/nonexistent/path/file.py"], allowed_tools=[],
        )
        ctx = self.fw._build_context(task)
        assert ctx == ""

    def test_returns_empty_for_empty_allowed_paths(self):
        task = FirewallTask(
            task_id="t4", instruction="analyze",
            allowed_paths=[], allowed_tools=[],
        )
        ctx = self.fw._build_context(task)
        assert ctx == ""


# ---------------------------------------------------------------------------
# ContextFirewall._build_command
# ---------------------------------------------------------------------------

class TestBuildCommand:
    def setup_method(self):
        self.fw = ContextFirewall()

    def _make_task(self, tools: list[str] | None = None) -> FirewallTask:
        return FirewallTask(
            task_id="t1",
            instruction="summarize",
            allowed_paths=[],
            allowed_tools=tools or ["Read"],
        )

    def test_uses_claude_p_form(self):
        cmd = self.fw._build_command(self._make_task(), "")
        assert cmd[0] == "claude"
        assert cmd[1] == "-p"

    def test_includes_instruction_in_prompt(self):
        task = self._make_task()
        cmd = self.fw._build_command(task, "")
        assert "summarize" in cmd[2]

    def test_includes_haiku_model(self):
        cmd = self.fw._build_command(self._make_task(), "")
        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-haiku-4-5-20251001"

    def test_includes_allowed_tools_joined(self):
        task = FirewallTask(
            task_id="t1", instruction="x",
            allowed_paths=[], allowed_tools=["Read", "Bash"],
        )
        cmd = self.fw._build_command(task, "")
        assert "--allowedTools" in cmd
        tools_idx = cmd.index("--allowedTools")
        assert cmd[tools_idx + 1] == "Read,Bash"


# ---------------------------------------------------------------------------
# ContextFirewall._parse_result
# ---------------------------------------------------------------------------

class TestParseResult:
    def setup_method(self):
        self.fw = ContextFirewall()

    def _mock_proc(self, returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_success_true_when_returncode_0(self):
        result = self.fw._parse_result("t1", self._mock_proc(0, "ok"), 10.0)
        assert result.success is True

    def test_success_false_when_returncode_1(self):
        result = self.fw._parse_result("t1", self._mock_proc(1, "", "err"), 10.0)
        assert result.success is False

    def test_error_populated_from_stderr_on_failure(self):
        result = self.fw._parse_result("t1", self._mock_proc(1, "", "something broke"), 10.0)
        assert result.error == "something broke"

    def test_duration_ms_matches_input(self):
        result = self.fw._parse_result("t1", self._mock_proc(0), 123.456)
        assert result.duration_ms == pytest.approx(123.456)

    def test_tokens_used_is_none(self):
        result = self.fw._parse_result("t1", self._mock_proc(0, "output"), 5.0)
        assert result.tokens_used is None


# ---------------------------------------------------------------------------
# ContextFirewall.run (subprocess mocked)
# ---------------------------------------------------------------------------

class TestContextFirewallRun:
    def setup_method(self):
        self.fw = ContextFirewall()

    def _task(self) -> FirewallTask:
        return FirewallTask(
            task_id="run-t1",
            instruction="analyze",
            allowed_paths=[],
            allowed_tools=["Read"],
        )

    def _mock_proc(self, returncode: int = 0, stdout: str = "result", stderr: str = "") -> MagicMock:
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_returns_firewall_result_on_success(self):
        with patch("agents.firewall.subprocess.run", return_value=self._mock_proc(0, "output")):
            result = self.fw.run(self._task())
        assert isinstance(result, FirewallResult)
        assert result.success is True
        assert result.output == "output"

    def test_returns_success_false_on_timeout(self):
        with patch("agents.firewall.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=120)):
            result = self.fw.run(self._task())
        assert result.success is False
        assert result.error == "timeout"

    def test_returns_success_false_on_any_exception(self):
        with patch("agents.firewall.subprocess.run", side_effect=Exception("boom")):
            result = self.fw.run(self._task())
        assert result.success is False
        assert "boom" in result.error

    def test_never_raises(self):
        with patch("agents.firewall.subprocess.run", side_effect=RuntimeError("crash")):
            result = self.fw.run(self._task())  # must not raise
        assert isinstance(result, FirewallResult)
```

- [ ] **Step 2.2: Run new tests — expect FAIL**

```bash
pytest hooks/tests/test_firewall.py::TestBuildContext hooks/tests/test_firewall.py::TestBuildCommand hooks/tests/test_firewall.py::TestParseResult hooks/tests/test_firewall.py::TestContextFirewallRun -v
```

Expected: `AttributeError: type object 'ContextFirewall' has no attribute...` or `ImportError`

- [ ] **Step 2.3: Add ContextFirewall to `agents/firewall.py`**

Append to the end of `agents/firewall.py` (after the dataclasses):

```python


class ContextFirewall:
    """Spawns an isolated sub-agent via `claude -p` as a context firewall.

    The main agent decides WHAT to do. The sub-agent executes in isolation
    with a minimal, purpose-built context — preventing cross-task contamination.
    """

    def run(self, task: FirewallTask) -> FirewallResult:
        """Spawn sub-agent. Never raises — returns success=False on any error."""
        start = time.monotonic()
        try:
            context = self._build_context(task)
            cmd = self._build_command(task, context)
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=task.timeout_seconds,
            )
            duration_ms = (time.monotonic() - start) * 1000
            return self._parse_result(task.task_id, proc, duration_ms)
        except subprocess.TimeoutExpired:
            return FirewallResult(
                task_id=task.task_id,
                success=False,
                output="",
                tokens_used=None,
                duration_ms=(time.monotonic() - start) * 1000,
                exit_code=1,
                error="timeout",
            )
        except Exception as exc:
            return FirewallResult(
                task_id=task.task_id,
                success=False,
                output="",
                tokens_used=None,
                duration_ms=(time.monotonic() - start) * 1000,
                exit_code=1,
                error=str(exc),
            )

    def _build_context(self, task: FirewallTask) -> str:
        """Reads allowed_paths, assembles context string, truncates to budget."""
        char_budget = task.context_budget * 4
        parts: list[str] = []
        used = 0
        for path in task.allowed_paths:
            try:
                content = Path(path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            entry = f"=== {path} ===\n{content}"
            remaining = char_budget - used
            if remaining <= 0:
                break
            if len(entry) > remaining:
                entry = entry[:remaining]
            parts.append(entry)
            used += len(entry)
        return "\n\n".join(parts)

    def _build_command(self, task: FirewallTask, context: str) -> list[str]:
        """Returns subprocess command list for `claude -p`."""
        prompt = f"{task.instruction}\n\n{context}" if context else task.instruction
        return [
            "claude", "-p", prompt,
            "--model", "claude-haiku-4-5-20251001",
            "--output-format", "text",
            "--allowedTools", ",".join(task.allowed_tools),
        ]

    def _parse_result(
        self, task_id: str, proc: subprocess.CompletedProcess, duration_ms: float
    ) -> FirewallResult:
        """Parses subprocess result into FirewallResult."""
        success = proc.returncode == 0
        return FirewallResult(
            task_id=task_id,
            success=success,
            output=proc.stdout or "",
            tokens_used=None,
            duration_ms=duration_ms,
            exit_code=proc.returncode,
            error=proc.stderr if not success else None,
        )
```

- [ ] **Step 2.4: Run tests — expect PASS**

```bash
pytest hooks/tests/test_firewall.py -v -k "not TestIsDelegatable and not TestPreTaskFirewallHook"
```

Expected: All tests pass (dataclass + ContextFirewall tests)

- [ ] **Step 2.5: Commit**

```bash
git -C /Users/vini/.claude/devflow add agents/firewall.py hooks/tests/test_firewall.py
git -C /Users/vini/.claude/devflow commit -m "feat(firewall): implement ContextFirewall with subprocess isolation"
```

---

## Task 3: TelemetryStore schema migration

**Files:**
- Modify: `telemetry/store.py`
- Modify: `hooks/tests/test_firewall.py` (add migration test)

- [ ] **Step 3.1: Add migration test to test_firewall.py**

Append to `hooks/tests/test_firewall.py`:

```python

# ---------------------------------------------------------------------------
# TelemetryStore schema migration
# ---------------------------------------------------------------------------

class TestTelemetryStoreMigration:
    def test_firewall_columns_exist_after_init(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from telemetry.store import TelemetryStore
        import sqlite3
        from contextlib import closing

        store = TelemetryStore(db_path=tmp_path / "test.db")
        with closing(sqlite3.connect(str(tmp_path / "test.db"))) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(task_executions)")}
        assert "firewall_delegated" in cols
        assert "firewall_task_id" in cols
        assert "firewall_success" in cols
        assert "firewall_duration_ms" in cols

    def test_firewall_columns_survive_double_init(self, tmp_path):
        """Second TelemetryStore(same db) must not crash (ADD COLUMN idempotent)."""
        from telemetry.store import TelemetryStore
        db = tmp_path / "test2.db"
        TelemetryStore(db_path=db)
        TelemetryStore(db_path=db)  # must not raise
```

- [ ] **Step 3.2: Run migration tests — expect FAIL**

```bash
pytest hooks/tests/test_firewall.py::TestTelemetryStoreMigration -v
```

Expected: `AssertionError: 'firewall_delegated' not in cols`

- [ ] **Step 3.3: Modify `telemetry/store.py`**

In `_COLUMNS` list, add after `"task_time_seconds"`:

```python
    "task_time_seconds",
    "firewall_delegated",
    "firewall_task_id",
    "firewall_success",
    "firewall_duration_ms",
```

In `_CREATE_TABLE` string, add before the closing `)`  (after `task_time_seconds`):

```sql
    task_time_seconds               INTEGER,
    firewall_delegated              BOOLEAN,
    firewall_task_id                TEXT,
    firewall_success                BOOLEAN,
    firewall_duration_ms            REAL
```

In `_init_schema`, after `conn.execute(_CREATE_TABLE)`, add migration for existing DBs:

```python
                conn.execute(_CREATE_TABLE)
                # Migrate existing databases — ADD COLUMN is idempotent via try/except
                _new_cols = [
                    ("firewall_delegated", "BOOLEAN"),
                    ("firewall_task_id", "TEXT"),
                    ("firewall_success", "BOOLEAN"),
                    ("firewall_duration_ms", "REAL"),
                ]
                for col, col_type in _new_cols:
                    try:
                        conn.execute(
                            f"ALTER TABLE task_executions ADD COLUMN {col} {col_type}"
                        )
                    except sqlite3.OperationalError:
                        pass  # column already exists
                conn.commit()
```

Remove the standalone `conn.commit()` that was on the line after `conn.execute(_CREATE_TABLE)` (it's replaced by the one inside the migration block).

- [ ] **Step 3.4: Run migration tests — expect PASS**

```bash
pytest hooks/tests/test_firewall.py::TestTelemetryStoreMigration -v
```

Expected: `2 passed`

- [ ] **Step 3.5: Run full test suite to confirm no regressions**

```bash
pytest hooks/tests/test_telemetry_store.py hooks/tests/test_firewall.py::TestTelemetryStoreMigration -v
```

Expected: All pass.

- [ ] **Step 3.6: Commit**

```bash
git -C /Users/vini/.claude/devflow add telemetry/store.py hooks/tests/test_firewall.py
git -C /Users/vini/.claude/devflow commit -m "feat(telemetry): add firewall columns to TelemetryStore schema"
```

---

## Task 4: pre_task_firewall.py hook

**Files:**
- Create: `hooks/pre_task_firewall.py`
- Modify: `hooks/tests/test_firewall.py` (add hook tests)

- [ ] **Step 4.1: Add _is_delegatable and hook tests to test_firewall.py**

Append to `hooks/tests/test_firewall.py`:

```python

# ---------------------------------------------------------------------------
# _is_delegatable
# ---------------------------------------------------------------------------

class TestIsDelegatable:
    def _import_hook(self):
        import importlib
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import pre_task_firewall
        importlib.reload(pre_task_firewall)
        return pre_task_firewall

    def test_read_tool_is_delegatable(self):
        m = self._import_hook()
        assert m._is_delegatable({"tool_name": "Read", "tool_input": {}}) is True

    def test_bash_with_grep_is_delegatable(self):
        m = self._import_hook()
        assert m._is_delegatable({
            "tool_name": "Bash",
            "tool_input": {"command": "grep -r foo ."},
        }) is True

    def test_bash_with_cat_is_delegatable(self):
        m = self._import_hook()
        assert m._is_delegatable({
            "tool_name": "Bash",
            "tool_input": {"command": "cat README.md"},
        }) is True

    def test_write_tool_is_not_delegatable(self):
        m = self._import_hook()
        assert m._is_delegatable({"tool_name": "Write", "tool_input": {}}) is False

    def test_edit_tool_is_not_delegatable(self):
        m = self._import_hook()
        assert m._is_delegatable({"tool_name": "Edit", "tool_input": {}}) is False

    def test_bash_with_write_command_is_not_delegatable(self):
        m = self._import_hook()
        assert m._is_delegatable({
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello > out.txt"},
        }) is False


# ---------------------------------------------------------------------------
# pre_task_firewall hook
# ---------------------------------------------------------------------------

class TestPreTaskFirewallHook:
    def _import_hook(self):
        import importlib
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import pre_task_firewall
        importlib.reload(pre_task_firewall)
        return pre_task_firewall

    def _write_risk_profile(self, state_dir: Path, oversight: str) -> None:
        (state_dir / "risk-profile.json").write_text(
            f'{{"oversight_level": "{oversight}"}}'
        )

    def test_prints_skipped_on_vibe(self, tmp_path, capsys):
        m = self._import_hook()
        self._write_risk_profile(tmp_path, "vibe")
        m.run(tmp_path, {"tool_name": "Read", "tool_input": {}})
        assert "skipped (vibe)" in capsys.readouterr().out

    def test_prints_delegated_false_on_standard(self, tmp_path, capsys):
        m = self._import_hook()
        self._write_risk_profile(tmp_path, "standard")
        m.run(tmp_path, {"tool_name": "Read", "tool_input": {}})
        out = capsys.readouterr().out
        assert "delegated=False" in out

    def test_delegates_read_on_strict(self, tmp_path, capsys):
        m = self._import_hook()
        self._write_risk_profile(tmp_path, "strict")
        mock_result = FirewallResult(
            task_id="x", success=True, output="ok",
            tokens_used=None, duration_ms=5.0, exit_code=0, error=None,
        )
        with patch("pre_task_firewall.ContextFirewall") as mock_fw_cls:
            mock_fw = MagicMock()
            mock_fw.run.return_value = mock_result
            mock_fw_cls.return_value = mock_fw
            m.run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x.py"}})
        mock_fw.run.assert_called_once()
        out = capsys.readouterr().out
        assert "delegated=True" in out

    def test_does_not_delegate_write_on_strict(self, tmp_path, capsys):
        m = self._import_hook()
        self._write_risk_profile(tmp_path, "strict")
        m.run(tmp_path, {"tool_name": "Write", "tool_input": {}})
        out = capsys.readouterr().out
        assert "delegated=False" in out

    def test_always_exits_0(self, tmp_path):
        m = self._import_hook()
        # No risk-profile.json at all — must not raise
        code = m.main()
        assert code == 0

    def test_updates_telemetry_on_delegation(self, tmp_path):
        m = self._import_hook()
        self._write_risk_profile(tmp_path, "strict")
        mock_result = FirewallResult(
            task_id="x", success=True, output="ok",
            tokens_used=None, duration_ms=5.0, exit_code=0, error=None,
        )
        mock_store = MagicMock()
        with patch("pre_task_firewall.ContextFirewall") as mock_fw_cls, \
             patch("pre_task_firewall.TelemetryStore", return_value=mock_store), \
             patch("pre_task_firewall.get_state_dir", return_value=tmp_path):
            mock_fw = MagicMock()
            mock_fw.run.return_value = mock_result
            mock_fw_cls.return_value = mock_fw
            m.run(tmp_path, {"tool_name": "Read", "tool_input": {}})
        mock_store.record.assert_called_once()
        payload = mock_store.record.call_args[0][0]
        assert payload["firewall_delegated"] is True
        assert payload["firewall_success"] is True
        assert "firewall_duration_ms" in payload
```

- [ ] **Step 4.2: Run new tests — expect FAIL**

```bash
pytest hooks/tests/test_firewall.py::TestIsDelegatable hooks/tests/test_firewall.py::TestPreTaskFirewallHook -v
```

Expected: `ModuleNotFoundError: No module named 'pre_task_firewall'`

- [ ] **Step 4.3: Create `hooks/pre_task_firewall.py`**

```python
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

from _util import get_session_id, get_state_dir, read_hook_stdin
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
    oversight_level = "standard"
    risk_path = state_dir / "risk-profile.json"
    if risk_path.exists():
        try:
            risk = json.loads(risk_path.read_text())
            oversight_level = risk.get("oversight_level", "standard")
        except (json.JSONDecodeError, OSError):
            pass

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
```

- [ ] **Step 4.4: Run all firewall tests — expect PASS**

```bash
pytest hooks/tests/test_firewall.py -v
```

Expected: All tests pass.

- [ ] **Step 4.5: Run full test suite — no regressions**

```bash
cd /Users/vini/.claude/devflow && pytest hooks/tests/ -q
```

Expected: All tests pass, no failures.

- [ ] **Step 4.6: Commit**

```bash
git -C /Users/vini/.claude/devflow add hooks/pre_task_firewall.py hooks/tests/test_firewall.py
git -C /Users/vini/.claude/devflow commit -m "feat(firewall): add pre_task_firewall hook with _is_delegatable detection"
```

---

## Self-Review Checklist

- [x] `FirewallTask` with `timeout_seconds=120`, `context_budget=4000` defaults ✓
- [x] `FirewallResult` with `tokens_used: int | None` ✓
- [x] `ContextFirewall.run()` never raises ✓
- [x] `_build_context` truncates to `context_budget * 4` chars ✓
- [x] `_build_context` skips missing files ✓
- [x] `_build_command` uses haiku + `--allowedTools` + `claude -p` ✓
- [x] `_parse_result` maps `returncode=0 → success=True` ✓
- [x] `pre_task_firewall.py` exits 0 always ✓
- [x] Skips on `oversight_level == "vibe"` ✓
- [x] Delegates only on `strict` or `human_review` ✓
- [x] `_is_delegatable`: Read=True, Bash+grep=True, Write=False, Edit=False ✓
- [x] TelemetryStore: 4 new columns + idempotent migration ✓
- [x] All test categories from spec covered ✓
