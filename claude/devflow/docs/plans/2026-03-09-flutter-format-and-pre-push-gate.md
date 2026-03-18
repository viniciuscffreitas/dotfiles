# Flutter Format + Pre-Push Gate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `dart format` to `_check_flutter()` in file_checker.py and create a new language-agnostic `pre_push_gate.py` hook that blocks `git push` when quality checks fail.

**Architecture:** Two changes to devflow's hook system: (1) enhance existing `_check_flutter()` to format+analyze (matching Go and Node.js behavior), (2) add new PreToolUse hook on Bash that intercepts `git push` commands and runs toolchain-specific quality gates before allowing the push.

**Tech Stack:** Python 3.10+, devflow hook JSON protocol, Claude Code hooks API (stdin JSON, stdout JSON with `hook_block`/`hook_context`)

---

### Task 1: Add `get_bash_command()` helper to `_util.py`

**Files:**
- Modify: `~/.claude/devflow/hooks/_util.py` (after `get_edited_file` function, ~line 108)
- Test: `~/.claude/devflow/hooks/tests/test_util.py`

**Step 1: Write the failing tests**

Add to `~/.claude/devflow/hooks/tests/test_util.py`:

```python
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
```

Also update the import at the top of test_util.py to include `get_bash_command`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/devflow && python3 -m pytest hooks/tests/test_util.py -v -k "get_bash_command"`
Expected: FAIL with ImportError (get_bash_command doesn't exist yet)

**Step 3: Implement `get_bash_command()` in `_util.py`**

Add after the `get_edited_file` function (~line 108):

```python
def get_bash_command(hook_data: dict) -> Optional[str]:
    cmd = hook_data.get("tool_input", {}).get("command")
    if cmd and cmd.strip():
        return cmd
    return None
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/devflow && python3 -m pytest hooks/tests/test_util.py -v -k "get_bash_command"`
Expected: 4 PASSED

**Step 5: Commit**

```bash
cd ~/.claude/devflow
git add hooks/_util.py hooks/tests/test_util.py
git commit -m "feat(hooks): add get_bash_command() helper to _util.py"
```

---

### Task 2: Add `dart format` to `_check_flutter()` in `file_checker.py`

**Files:**
- Modify: `~/.claude/devflow/hooks/file_checker.py:90-99` (`_check_flutter` function)
- Test: `~/.claude/devflow/hooks/tests/test_file_checker.py`

**Step 1: Write the failing tests**

Add to `~/.claude/devflow/hooks/tests/test_file_checker.py`:

```python
from unittest.mock import patch, MagicMock
from file_checker import _check_flutter


def test_flutter_checker_formats_dart_file(tmp_path, monkeypatch):
    """dart format should be called for .dart files."""
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/dart" if x == "dart" else None)
    f = tmp_path / "widget.dart"
    f.write_text("class  Widget {}")

    calls = []
    original_run = __import__("_util").run_command

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return 0, ""

    monkeypatch.setattr("file_checker.run_command", fake_run)
    _check_flutter(f, tmp_path)

    # Should call dart format first, then dart analyze
    assert any("format" in str(c) for c in calls), f"Expected dart format call, got: {calls}"
    assert any("analyze" in str(c) for c in calls), f"Expected dart analyze call, got: {calls}"


def test_flutter_checker_format_before_analyze(tmp_path, monkeypatch):
    """dart format must run BEFORE dart analyze."""
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/dart" if x == "dart" else None)
    f = tmp_path / "widget.dart"
    f.write_text("class Widget {}")

    call_order = []

    def fake_run(cmd, **kwargs):
        if "format" in cmd:
            call_order.append("format")
        elif "analyze" in cmd:
            call_order.append("analyze")
        return 0, ""

    monkeypatch.setattr("file_checker.run_command", fake_run)
    _check_flutter(f, tmp_path)

    assert call_order == ["format", "analyze"]


def test_flutter_checker_no_dart_binary(tmp_path, monkeypatch):
    """When dart is not installed, returns no issues."""
    monkeypatch.setattr(shutil, "which", lambda x: None)
    f = tmp_path / "widget.dart"
    f.write_text("class Widget {}")
    issues = _check_flutter(f, tmp_path)
    assert issues == []
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/devflow && python3 -m pytest hooks/tests/test_file_checker.py -v -k "flutter"`
Expected: FAIL (dart format not called)

**Step 3: Modify `_check_flutter()` to format + analyze**

Replace the `_check_flutter` function in `file_checker.py`:

```python
def _check_flutter(file_path: Path, project_root: Path) -> list[str]:
    issues = []
    if not shutil.which("dart"):
        return issues
    # Format first (like gofmt -w and prettier --write)
    run_command(["dart", "format", str(file_path)], cwd=project_root, timeout=15)
    # Then analyze
    code, output = run_command(["dart", "analyze", str(file_path)], cwd=project_root, timeout=30)
    if code != 0 and output:
        lines = [l for l in output.splitlines() if "error" in l.lower() or "warning" in l.lower()]
        if lines:
            issues.append("Dart: " + "\n".join(lines[:10]))
    return issues
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/devflow && python3 -m pytest hooks/tests/test_file_checker.py -v`
Expected: ALL PASSED (existing + new tests)

**Step 5: Commit**

```bash
cd ~/.claude/devflow
git add hooks/file_checker.py hooks/tests/test_file_checker.py
git commit -m "feat(hooks): add dart format to _check_flutter() — align with Go/Node.js behavior"
```

---

### Task 3: Create `pre_push_gate.py` hook

**Files:**
- Create: `~/.claude/devflow/hooks/pre_push_gate.py`
- Create: `~/.claude/devflow/hooks/tests/test_pre_push_gate.py`

**Step 1: Write the failing tests**

Create `~/.claude/devflow/hooks/tests/test_pre_push_gate.py`:

```python
import json
import sys
from pathlib import Path
from unittest.mock import patch

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


def test_quality_commands_nodejs(tmp_path):
    cmds = get_quality_commands(ToolchainKind.NODEJS, tmp_path)
    assert len(cmds) >= 1
    assert any("lint" in c["label"].lower() for c in cmds)


def test_quality_commands_go(tmp_path):
    cmds = get_quality_commands(ToolchainKind.GO, tmp_path)
    assert any("vet" in c["label"] for c in cmds)


def test_quality_commands_unknown(tmp_path):
    cmds = get_quality_commands(None, tmp_path)
    assert cmds == []
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/devflow && python3 -m pytest hooks/tests/test_pre_push_gate.py -v`
Expected: FAIL (module not found)

**Step 3: Create `pre_push_gate.py`**

Create `~/.claude/devflow/hooks/pre_push_gate.py`:

```python
"""
PreToolUse hook (Bash) — language-agnostic pre-push quality gate.
Intercepts `git push` commands and runs toolchain-specific quality checks.
Blocks the push if any check fails.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _util import (
    ToolchainKind,
    detect_toolchain,
    get_bash_command,
    hook_block,
    read_hook_stdin,
    run_command,
)

_GIT_PUSH_RE = re.compile(r"^\s*git\s+push\b")


def should_gate(command: Optional[str]) -> bool:
    if not command:
        return False
    return bool(_GIT_PUSH_RE.match(command))


def get_quality_commands(
    toolchain: Optional[ToolchainKind], project_root: Path,
) -> list[dict]:
    if toolchain == ToolchainKind.FLUTTER:
        return [
            {
                "label": "dart format",
                "cmd": ["dart", "format", "--output=none", "--set-exit-if-changed", "."],
                "timeout": 60,
            },
            {
                "label": "flutter analyze",
                "cmd": ["flutter", "analyze"],
                "timeout": 120,
            },
        ]
    if toolchain == ToolchainKind.NODEJS:
        cmds = []
        pkg_json = project_root / "package.json"
        if pkg_json.exists():
            import json
            try:
                scripts = json.loads(pkg_json.read_text()).get("scripts", {})
                if "lint" in scripts:
                    npm = "npm"
                    cmds.append({"label": "npm lint", "cmd": [npm, "run", "lint"], "timeout": 60})
            except (json.JSONDecodeError, OSError):
                pass
        if not cmds:
            eslint = shutil.which("eslint")
            if eslint:
                cmds.append({"label": "eslint", "cmd": [eslint, "."], "timeout": 60})
        return cmds
    if toolchain == ToolchainKind.GO:
        cmds = []
        if shutil.which("go"):
            cmds.append({"label": "go vet", "cmd": ["go", "vet", "./..."], "timeout": 60})
        return cmds
    if toolchain == ToolchainKind.RUST:
        cmds = []
        if shutil.which("cargo"):
            cmds.append({"label": "cargo check", "cmd": ["cargo", "check"], "timeout": 120})
        return cmds
    if toolchain == ToolchainKind.MAVEN:
        mvnw = project_root / "mvnw"
        mvn = str(mvnw) if mvnw.exists() else shutil.which("mvn")
        if mvn:
            return [{"label": "mvn compile", "cmd": [mvn, "compile", "-q"], "timeout": 120}]
    return []


def main() -> int:
    hook_data = read_hook_stdin()
    command = get_bash_command(hook_data)

    if not should_gate(command):
        return 0

    toolchain, project_root = detect_toolchain(Path.cwd())
    if not toolchain or not project_root:
        return 0

    quality_cmds = get_quality_commands(toolchain, project_root)
    if not quality_cmds:
        return 0

    for qc in quality_cmds:
        code, output = run_command(qc["cmd"], cwd=project_root, timeout=qc["timeout"])
        if code != 0:
            msg = f"Pre-push gate BLOCKED: {qc['label']} failed.\n"
            if output:
                msg += output[:500]
            print(hook_block(msg))
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/devflow && python3 -m pytest hooks/tests/test_pre_push_gate.py -v`
Expected: ALL PASSED

**Step 5: Commit**

```bash
cd ~/.claude/devflow
git add hooks/pre_push_gate.py hooks/tests/test_pre_push_gate.py
git commit -m "feat(hooks): add pre_push_gate.py — language-agnostic pre-push quality gate"
```

---

### Task 4: Register `pre_push_gate.py` in `install.sh`

**Files:**
- Modify: `~/.claude/devflow/install.sh:56-101` (DEVFLOW_HOOKS dict in the Python script)

**Step 1: Add PreToolUse entry to DEVFLOW_HOOKS**

In `install.sh`, inside the Python script's `DEVFLOW_HOOKS` dict, add a new entry after `"Stop"`:

```python
    "PreToolUse": [
        {
            "matcher": "Bash",
            "hooks": [
                {"type": "command", "command": f"python3 {devflow_dir}/hooks/pre_push_gate.py"},
            ]
        },
    ],
```

**Step 2: Update the install success message**

Change the line:
```
    echo "  - 7 automatic hooks (quality, TDD, context, compaction, stop guard)"
```
to:
```
    echo "  - 8 automatic hooks (quality, TDD, context, compaction, stop guard, pre-push gate)"
```

**Step 3: Run install to register the new hook**

Run: `cd ~/.claude/devflow && bash install.sh`
Expected: All tests pass, hooks registered

**Step 4: Verify the hook is in `~/.claude/settings.json`**

Run: `cat ~/.claude/settings.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['hooks'].get('PreToolUse', []), indent=2))"`
Expected: JSON array containing the pre_push_gate.py entry (alongside any existing PreToolUse hooks like dippy-hook)

**Step 5: Commit**

```bash
cd ~/.claude/devflow
git add install.sh
git commit -m "feat(install): register pre_push_gate.py as PreToolUse hook"
```

---

### Task 5: Remove redundant project-level hooks from momease

**Files:**
- Delete: `/Users/vini/Developer/momease/mom-ease/.claude/hooks/dart-format-file.sh`
- Delete: `/Users/vini/Developer/momease/mom-ease/.claude/hooks/dart-format-after-merge.sh`
- Delete: `/Users/vini/Developer/momease/mom-ease/.claude/hooks/pre-push-gate.sh`
- Modify: `/Users/vini/Developer/momease/mom-ease/.claude/settings.json` (remove hooks section)

**Why:** These are now redundant — devflow handles everything globally:
- `dart-format-file.sh` → replaced by `file_checker.py` (now does format+analyze)
- `dart-format-after-merge.sh` → still handled by learned skill (knowledge), and file_checker catches unformatted files on next edit
- `pre-push-gate.sh` → replaced by `pre_push_gate.py`

**Step 1: Remove the hook files**

```bash
rm /Users/vini/Developer/momease/mom-ease/.claude/hooks/dart-format-file.sh
rm /Users/vini/Developer/momease/mom-ease/.claude/hooks/dart-format-after-merge.sh
rm /Users/vini/Developer/momease/mom-ease/.claude/hooks/pre-push-gate.sh
rmdir /Users/vini/Developer/momease/mom-ease/.claude/hooks/ 2>/dev/null || true
```

**Step 2: Remove hooks from project settings.json**

Remove the entire `hooks` key from `/Users/vini/Developer/momease/mom-ease/.claude/settings.json`, leaving the file empty or removing it if it had no other content.

```bash
rm /Users/vini/Developer/momease/mom-ease/.claude/settings.json
```

**Step 3: Verify devflow hooks still work**

Run: `cd /Users/vini/Developer/momease/mom-ease && echo '{"tool_input":{"command":"git push origin develop"}}' | python3 ~/.claude/devflow/hooks/pre_push_gate.py 2>&1`
Expected: Pre-push gate runs format+analyze checks

**Step 4: No commit needed** — these files were never committed to the momease repo

---

### Task 6: Run full test suite and verify

**Step 1: Run all devflow tests**

Run: `cd ~/.claude/devflow && python3 -m pytest hooks/tests/ -v`
Expected: ALL PASSED (existing + new tests)

**Step 2: Run a manual integration test**

```bash
cd /Users/vini/Developer/momease/mom-ease
# Test file_checker with dart format
echo '{"tool_input":{"file_path":"/Users/vini/Developer/momease/mom-ease/lib/main.dart"}}' | python3 ~/.claude/devflow/hooks/file_checker.py

# Test pre_push_gate
echo '{"tool_input":{"command":"git push origin develop"}}' | python3 ~/.claude/devflow/hooks/pre_push_gate.py
```

**Step 3: Push devflow changes**

```bash
cd ~/.claude/devflow
git push origin main
```
