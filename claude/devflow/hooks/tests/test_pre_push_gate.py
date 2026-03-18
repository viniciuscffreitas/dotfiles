import json
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
