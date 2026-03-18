import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from _util import (
    check_file_length,
    detect_toolchain,
    get_bash_command,
    get_edited_file,
    hook_block,
    hook_context,
    hook_deny,
    run_command,
    ToolchainKind,
)


# --- check_file_length ---

def test_file_length_ok(tmp_path):
    f = tmp_path / "small.py"
    f.write_text("\n".join(["line"] * 50))
    warn, critical, count = check_file_length(f)
    assert not warn and not critical
    assert count == 50


def test_file_length_warn(tmp_path):
    f = tmp_path / "big.py"
    f.write_text("\n".join(["line"] * 450))
    warn, critical, count = check_file_length(f)
    assert warn and not critical
    assert count == 450


def test_file_length_critical(tmp_path):
    f = tmp_path / "huge.py"
    f.write_text("\n".join(["line"] * 650))
    warn, critical, count = check_file_length(f)
    assert critical
    assert count == 650


def test_file_length_missing():
    warn, critical, count = check_file_length(Path("/nonexistent/file.py"))
    assert not warn and not critical and count == 0


# --- detect_toolchain ---

def test_detect_nodejs(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    kind, root = detect_toolchain(tmp_path)
    assert kind == ToolchainKind.NODEJS
    assert root == tmp_path


def test_detect_flutter(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: app")
    kind, root = detect_toolchain(tmp_path)
    assert kind == ToolchainKind.FLUTTER
    assert root == tmp_path


def test_detect_maven(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>")
    kind, root = detect_toolchain(tmp_path)
    assert kind == ToolchainKind.MAVEN
    assert root == tmp_path


def test_detect_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]")
    kind, root = detect_toolchain(tmp_path)
    assert kind == ToolchainKind.RUST
    assert root == tmp_path


def test_detect_go(tmp_path):
    (tmp_path / "go.mod").write_text("module app")
    kind, root = detect_toolchain(tmp_path)
    assert kind == ToolchainKind.GO
    assert root == tmp_path


def test_detect_none(tmp_path):
    kind, root = detect_toolchain(tmp_path)
    assert kind is None
    assert root is None


def test_nodejs_priority_over_maven(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "pom.xml").write_text("<project/>")
    kind, root = detect_toolchain(tmp_path)
    assert kind == ToolchainKind.NODEJS


def test_detect_parent_traversal(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    child = tmp_path / "src" / "deep"
    child.mkdir(parents=True)
    kind, root = detect_toolchain(child)
    assert kind == ToolchainKind.NODEJS
    assert root == tmp_path


# --- get_edited_file ---

def test_get_edited_file_present():
    result = get_edited_file({"tool_input": {"file_path": "/tmp/x.py"}})
    assert result == Path("/tmp/x.py")


def test_get_edited_file_missing():
    assert get_edited_file({}) is None


def test_get_edited_file_no_tool_input():
    assert get_edited_file({"other": "data"}) is None


# --- run_command ---

def test_run_command_success():
    code, output = run_command(["echo", "hello"])
    assert code == 0
    assert "hello" in output


def test_run_command_not_found():
    code, msg = run_command(["nonexistent_binary_xyz_12345"])
    assert code == 127
    assert "not found" in msg.lower()


def test_run_command_timeout():
    code, msg = run_command(["sleep", "10"], timeout=1)
    assert code == 1
    assert "timeout" in msg


# --- hook JSON builders ---

def test_hook_context_json():
    result = json.loads(hook_context("test message"))
    assert result["hookSpecificOutput"]["additionalContext"] == "test message"
    assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_hook_context_custom_event():
    result = json.loads(hook_context("msg", event_name="Stop"))
    assert result["hookSpecificOutput"]["hookEventName"] == "Stop"


def test_hook_block_json():
    result = json.loads(hook_block("blocked"))
    assert result["decision"] == "block"
    assert result["reason"] == "blocked"


def test_hook_deny_json():
    result = json.loads(hook_deny("denied"))
    assert result["permissionDecision"] == "deny"
    assert result["reason"] == "denied"


# --- get_bash_command ---

def test_get_bash_command_present():
    result = get_bash_command({"tool_input": {"command": "git push origin main"}})
    assert result == "git push origin main"


def test_get_bash_command_missing():
    assert get_bash_command({}) is None


def test_get_bash_command_no_tool_input():
    assert get_bash_command({"other": "data"}) is None


def test_get_bash_command_empty():
    assert get_bash_command({"tool_input": {"command": ""}}) is None
