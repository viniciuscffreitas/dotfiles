"""Tests for ContextFirewall and pre_task_firewall hook."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import subprocess
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# TelemetryStore schema migration
# ---------------------------------------------------------------------------

class TestTelemetryStoreMigration:
    def test_firewall_columns_exist_after_init(self, tmp_path):
        import sqlite3
        from contextlib import closing
        from telemetry.store import TelemetryStore

        store = TelemetryStore(db_path=tmp_path / "test.db")
        with closing(sqlite3.connect(str(tmp_path / "test.db"))) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(task_executions)")}
        assert "firewall_delegated" in cols
        assert "firewall_task_id" in cols
        assert "firewall_success" in cols
        assert "firewall_duration_ms" in cols

    def test_firewall_columns_survive_double_init(self, tmp_path):
        from telemetry.store import TelemetryStore
        db = tmp_path / "test2.db"
        TelemetryStore(db_path=db)
        TelemetryStore(db_path=db)  # must not raise


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
