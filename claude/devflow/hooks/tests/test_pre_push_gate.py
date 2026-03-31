import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pre_push_gate import should_gate, get_quality_commands
from _util import ToolchainKind


# --- should_gate ---

def test_should_gate_git_push():
    assert should_gate("git push origin main")


def test_should_gate_git_push_with_flags():
    assert should_gate("git push -u origin feature/branch")


def test_should_gate_git_push_force():
    assert should_gate("git push --force-with-lease origin main")


def test_should_not_gate_git_status():
    assert not should_gate("git status")


def test_should_not_gate_git_pull():
    assert not should_gate("git pull origin main")


def test_should_not_gate_git_merge():
    assert not should_gate("git merge feature")


def test_should_not_gate_empty():
    assert not should_gate("")


def test_should_not_gate_none():
    assert not should_gate(None)


def test_should_not_gate_non_git():
    assert not should_gate("echo git push")


# --- get_quality_commands ---

def test_quality_commands_flutter(tmp_path):
    cmds = get_quality_commands(ToolchainKind.FLUTTER, tmp_path)
    assert len(cmds) == 2
    assert cmds[0]["label"] == "dart format"
    assert cmds[1]["label"] == "flutter analyze"


def test_quality_commands_go(tmp_path):
    cmds = get_quality_commands(ToolchainKind.GO, tmp_path)
    assert any("vet" in c["label"] for c in cmds)


def test_quality_commands_unknown(tmp_path):
    cmds = get_quality_commands(None, tmp_path)
    assert cmds == []


def test_quality_commands_python_returns_pytest(tmp_path, monkeypatch):
    """Python project must run pytest."""
    monkeypatch.setattr(shutil, "which", lambda x: None)
    cmds = get_quality_commands(ToolchainKind.PYTHON, tmp_path)
    assert len(cmds) >= 1
    assert cmds[0]["label"] == "pytest"
    assert "python3" in cmds[0]["cmd"]
    assert "-m" in cmds[0]["cmd"]
    assert "pytest" in cmds[0]["cmd"]


def test_quality_commands_python_pytest_flags(tmp_path, monkeypatch):
    """pytest must run with --tb=short -q."""
    monkeypatch.setattr(shutil, "which", lambda x: None)
    cmds = get_quality_commands(ToolchainKind.PYTHON, tmp_path)
    pytest_cmd = cmds[0]["cmd"]
    assert "--tb=short" in pytest_cmd
    assert "-q" in pytest_cmd


def test_quality_commands_python_includes_mypy_when_available(tmp_path, monkeypatch):
    """When mypy is on PATH, it is added as second check."""
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/mypy" if x == "mypy" else None)
    cmds = get_quality_commands(ToolchainKind.PYTHON, tmp_path)
    assert len(cmds) == 2
    assert cmds[1]["label"] == "mypy"
    assert "--ignore-missing-imports" in cmds[1]["cmd"]


def test_quality_commands_python_skips_mypy_gracefully(tmp_path, monkeypatch):
    """When mypy is not on PATH, only pytest is returned."""
    monkeypatch.setattr(shutil, "which", lambda x: None)
    cmds = get_quality_commands(ToolchainKind.PYTHON, tmp_path)
    assert len(cmds) == 1
    assert all("mypy" not in c["label"] for c in cmds)


def test_quality_commands_non_python_no_pytest(tmp_path, monkeypatch):
    """Non-Python toolchains must not include pytest."""
    monkeypatch.setattr(shutil, "which", lambda x: None)
    for kind in [ToolchainKind.FLUTTER, ToolchainKind.GO, ToolchainKind.RUST]:
        cmds = get_quality_commands(kind, tmp_path)
        assert all("pytest" not in c["label"] for c in cmds), \
            f"pytest found in {kind} commands: {cmds}"
