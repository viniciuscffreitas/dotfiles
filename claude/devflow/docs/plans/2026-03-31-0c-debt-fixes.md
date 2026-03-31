# 0C Debt Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four independent technical debt items (cross-session spec contamination, pre_compact heuristic, Python toolchain support, and state directory pollution) in a single commit.

**Architecture:** All fixes are in the devflow hooks system at `/Users/vini/.claude/devflow/hooks/`. Each fix is self-contained: modify the hook, add/replace tests, verify green. Fixes 1–3 add behavior; Fix 4 removes test artefacts. Single atomic commit at the end.

**Tech Stack:** Python 3.13, pytest, unittest.mock — no new dependencies. Test runner: `python3.13 -m pytest hooks/tests/ -q`.

---

## File Map

| Fix | Files Modified | Files Created |
|-----|----------------|---------------|
| Fix 1 | `hooks/spec_stop_guard.py`, `hooks/tests/test_spec_stop_guard.py` | — |
| Fix 2 | `hooks/pre_compact.py`, `hooks/tests/test_compact_hooks.py` | — |
| Fix 3 | `hooks/_util.py`, `hooks/file_checker.py`, `hooks/pre_push_gate.py`, `hooks/tests/test_file_checker.py`, `hooks/tests/test_pre_push_gate.py`, `hooks/tests/test_util.py` | — |
| Fix 4 | (shell: delete artefact dirs) | — |
| Docs | `docs/audit-20260331.md` | — |

**Baseline:** 292 tests passing. **Target:** ≥320 tests passing.

---

## Task 1: Fix spec_stop_guard.py — cross-session contamination

### Context
`spec_stop_guard.py` currently blocks session exit whenever `active-spec.json` has an active spec. The bug: when `$CLAUDE_SESSION_ID` is empty or `"default"`, ALL sessions share `state/default/active-spec.json`, so a spec from session A blocks exit in session B (different project entirely).

Three independent fixes:
1. Session bypass: if session ID is empty or "default" → skip guard entirely
2. COMPLETED cleanup: delete `active-spec.json` when status is COMPLETED (don't leave stale files)
3. cwd ownership check: if the spec's `cwd` field doesn't match `os.getcwd()` → bypass

**Files:**
- Modify: `hooks/spec_stop_guard.py`
- Modify: `hooks/tests/test_spec_stop_guard.py`

---

- [ ] **Step 1.1: Write the failing tests**

Add these 8 tests to `hooks/tests/test_spec_stop_guard.py` (after the existing tests):

```python
import os  # add at top if not present


# --- Fix 1a: session ID bypass ---

def test_empty_session_id_bypasses_guard(tmp_path, capsys, monkeypatch):
    """When CLAUDE_SESSION_ID is empty, guard must not block and must not read state."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    with (
        patch("spec_stop_guard.get_state_dir", return_value=tmp_path),
        patch("spec_stop_guard._has_active_spec") as mock_has_spec,
    ):
        rc = main()
    assert rc == 0
    assert "block" not in capsys.readouterr().out
    mock_has_spec.assert_not_called()


def test_default_session_id_bypasses_guard(tmp_path, capsys, monkeypatch):
    """Session ID 'default' is unsafe for isolation — guard must bypass."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "default")
    with (
        patch("spec_stop_guard.get_state_dir", return_value=tmp_path),
        patch("spec_stop_guard._has_active_spec") as mock_has_spec,
    ):
        rc = main()
    assert rc == 0
    assert "block" not in capsys.readouterr().out
    mock_has_spec.assert_not_called()


# --- Fix 1b: COMPLETED deletes file ---

def test_completed_spec_deletes_file(tmp_path):
    """_has_active_spec must delete active-spec.json when status is COMPLETED."""
    state_dir = _make_state_dir(tmp_path)
    spec_file = state_dir / "active-spec.json"
    spec = {"status": "COMPLETED", "plan_path": "/plans/done.md"}
    spec_file.write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active
    assert not spec_file.exists()


def test_completed_spec_returns_not_active(tmp_path):
    """Return value is (False, '') for COMPLETED — same as before, file deleted as side effect."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "COMPLETED", "plan_path": "/plans/done.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active
    assert desc == ""


# --- Fix 1c: cwd ownership ---

def test_cwd_mismatch_bypasses_guard(tmp_path, monkeypatch):
    """Spec from a different project (cwd mismatch) must not block this session."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/task.md", "cwd": "/other/project"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    monkeypatch.chdir(tmp_path)  # current dir is tmp_path, not /other/project
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active


def test_cwd_match_still_blocks(tmp_path, monkeypatch):
    """Spec with matching cwd must still block — ownership confirmed."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/task.md", "cwd": str(tmp_path)}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    monkeypatch.chdir(tmp_path)
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active
    assert "task.md" in desc


def test_spec_without_cwd_field_still_blocks(tmp_path):
    """Old specs without a cwd field must still block (backwards compatibility)."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/legacy.md"}  # no cwd field
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active


def test_cwd_empty_string_does_not_bypass(tmp_path):
    """Empty cwd string in spec is treated as 'not set' — no bypass, backwards compat."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/task.md", "cwd": ""}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active
```

- [ ] **Step 1.2: Run tests — verify 8 new tests FAIL**

```
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_spec_stop_guard.py -q
```

Expected: 8 failures, 10 existing tests still pass (18 total, 8 FAIL).

- [ ] **Step 1.3: Implement the fix in spec_stop_guard.py**

Replace the full content of `hooks/spec_stop_guard.py`:

```python
"""
Stop hook — blocks session exit if an active spec is IMPLEMENTING, PENDING, or in_progress.
Also cleans up the discovery-ran marker so no future session inherits stale state.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_state_dir, hook_block

# Specs older than 24 hours are considered abandoned
SPEC_EXPIRY_SECONDS = 24 * 60 * 60


def _has_active_spec() -> tuple[bool, str]:
    state_dir = get_state_dir()
    active_file = state_dir / "active-spec.json"
    if active_file.exists():
        try:
            data = json.loads(active_file.read_text())
            status = data.get("status", "")

            if status == "COMPLETED":
                active_file.unlink(missing_ok=True)
                return False, ""

            if status in ("IMPLEMENTING", "PENDING", "in_progress"):
                # Check cwd ownership — if present and mismatched, spec belongs to another project
                spec_cwd = data.get("cwd")
                if spec_cwd and spec_cwd != os.getcwd():
                    return False, ""

                # Check timestamp — abandon if too old
                started_at = data.get("started_at", 0)
                if started_at and (time.time() - started_at) > SPEC_EXPIRY_SECONDS:
                    return False, ""
                plan_path = data.get("plan_path", "unknown")
                return True, f"{plan_path} ({status})"
        except (json.JSONDecodeError, OSError) as e:
            # Fail-safe: corrupt file should NOT block forever
            # Check file age as fallback
            try:
                file_age = time.time() - active_file.stat().st_mtime
                if file_age > SPEC_EXPIRY_SECONDS:
                    return False, ""
            except OSError:
                pass
            print(f"[devflow] WARNING: could not read active-spec, assuming active: {e}", file=sys.stderr)
            return True, "unknown (corrupt state file)"
    return False, ""


def _cleanup_discovery_marker() -> None:
    state_dir = get_state_dir()
    marker = state_dir / "discovery-ran"
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    session_id = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if not session_id or session_id == "default":
        print("[devflow] no session ID — guard bypassed", file=sys.stderr)
        _cleanup_discovery_marker()
        return 0

    active, description = _has_active_spec()
    if active:
        reason = (
            f"[devflow] Active spec detected: {description}\n"
            f"Complete it or use /pause to explicitly pause.\n"
            f"After /pause, session exit will be allowed."
        )
        print(hook_block(reason))

    _cleanup_discovery_marker()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 1.4: Run tests — verify all pass**

```
python3.13 -m pytest hooks/tests/test_spec_stop_guard.py -q
```

Expected: 18 passed (10 existing + 8 new).

- [ ] **Step 1.5: Run full suite — no regressions**

```
python3.13 -m pytest hooks/tests/ -q
```

Expected: ≥300 passed (292 baseline + 8 new).

---

## Task 2: Fix pre_compact.py — replace text-scanning heuristic

### Context
`_find_active_spec()` currently scans `~/.claude/plans/*.md` looking for the string `"IMPLEMENTING"`. This is fragile — any plan file that *discusses* implementing something produces a false positive. The correct source of truth is `active-spec.json`, which `spec_stop_guard` already uses.

**Files:**
- Modify: `hooks/pre_compact.py`
- Modify: `hooks/tests/test_compact_hooks.py`

---

- [ ] **Step 2.1: Write the failing tests + remove obsolete tests**

In `hooks/tests/test_compact_hooks.py`:
1. Delete the 4 old `_find_active_spec` tests (they patch `Path.home`, which the new impl ignores)
2. Add 8 new tests

The file after changes should look like:

```python
"""Tests for pre_compact.py and post_compact_restore.py — tested together as they share state."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent))

from pre_compact import _find_active_spec
from post_compact_restore import main as restore_main


# --- pre_compact: _find_active_spec (reads active-spec.json via get_state_dir) ---

def test_find_active_spec_returns_plan_path_for_implementing(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "IMPLEMENTING", "plan_path": "/plans/feat.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is not None
    assert result["plan_path"] == "/plans/feat.md"


def test_find_active_spec_returns_implementing_status(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "IMPLEMENTING", "plan_path": "/plans/feat.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is not None
    assert result["status"] == "IMPLEMENTING"


def test_find_active_spec_returns_none_when_no_file(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    # No active-spec.json created
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_returns_none_for_pending(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "PENDING", "plan_path": "/plans/task.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_returns_none_for_completed(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "COMPLETED", "plan_path": "/plans/done.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_returns_none_for_invalid_json(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    (state_dir / "active-spec.json").write_text("{invalid json!!!")
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_does_not_scan_md_files(tmp_path):
    """Verify no filesystem glob scanning of .md files occurs."""
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "IMPLEMENTING", "plan_path": "/plans/feat.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with (
        patch("pre_compact.get_state_dir", return_value=state_dir),
        patch.object(Path, "glob") as mock_glob,
    ):
        _find_active_spec()
    mock_glob.assert_not_called()


def test_find_active_spec_returns_none_for_paused(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "PAUSED", "plan_path": "/plans/paused.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


# --- post_compact_restore (unchanged) ---

def test_restore_with_active_spec(tmp_path, capsys):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    state = {
        "session_id": "test",
        "active_spec": {"plan_path": "/plans/feat.md", "status": "IMPLEMENTING"},
        "cwd": "/home/user/project",
    }
    (state_dir / "pre-compact.json").write_text(json.dumps(state))
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        code = restore_main()
    assert code == 0
    output = capsys.readouterr().out
    assert "Context Restored" in output
    assert "feat.md" in output
    assert "IMPLEMENTING" in output
    assert "/home/user/project" in output


def test_restore_no_spec(tmp_path, capsys):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    state = {"session_id": "test", "active_spec": None, "cwd": "/tmp"}
    (state_dir / "pre-compact.json").write_text(json.dumps(state))
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        code = restore_main()
    assert code == 0
    output = capsys.readouterr().out
    assert "No active spec" in output


def test_restore_no_state_file(tmp_path, capsys):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        code = restore_main()
    assert code == 0
    assert capsys.readouterr().out == ""


def test_restore_deletes_state_file(tmp_path):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "pre-compact.json"
    state_file.write_text(json.dumps({"session_id": "test", "active_spec": None}))
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        restore_main()
    assert not state_file.exists()


def test_restore_corrupt_json(tmp_path, capsys):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    (state_dir / "pre-compact.json").write_text("{corrupt json!!!")
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        code = restore_main()
    assert code == 0
    assert capsys.readouterr().out == ""
```

- [ ] **Step 2.2: Run tests — verify 8 new tests FAIL, post_compact tests still pass**

```
python3.13 -m pytest hooks/tests/test_compact_hooks.py -q
```

Expected: 8 FAIL (new _find_active_spec tests), 5 pass (post_compact_restore tests).

- [ ] **Step 2.3: Implement the fix in pre_compact.py**

Replace `_find_active_spec()` function in `hooks/pre_compact.py`:

```python
def _find_active_spec() -> dict | None:
    state_dir = get_state_dir()
    active_file = state_dir / "active-spec.json"
    if not active_file.exists():
        return None
    try:
        data = json.loads(active_file.read_text())
        if data.get("status") != "IMPLEMENTING":
            return None
        return {"plan_path": data.get("plan_path", ""), "status": "IMPLEMENTING"}
    except (json.JSONDecodeError, OSError):
        return None
```

Note: The old `safe_mtime` helper and the `plans_dir` logic are removed entirely. Also remove the now-unused `import os` if it becomes unreferenced (check `main()` still uses `os.getcwd()`). Actually `main()` uses `os.getcwd()` so keep it.

- [ ] **Step 2.4: Run tests — verify all pass**

```
python3.13 -m pytest hooks/tests/test_compact_hooks.py -q
```

Expected: 13 passed (8 new + 5 post_compact).

- [ ] **Step 2.5: Run full suite — no regressions**

```
python3.13 -m pytest hooks/tests/ -q
```

Expected: ≥308 passed.

---

## Task 3: Python toolchain support in file_checker and pre_push_gate

### Context
`file_checker.py` supports Node.js, Flutter, Go, Rust, Maven — but not Python. `pre_push_gate.py` has the same gap. Given devflow itself is Python, this is the most ironic omission in the audit. The fix adds `ToolchainKind.PYTHON` to `_util.py`, `_check_python()` to `file_checker.py`, and Python quality commands to `pre_push_gate.py`.

**Files:**
- Modify: `hooks/_util.py` (add PYTHON enum + fingerprints)
- Modify: `hooks/file_checker.py` (add `_check_python`, register in `_CHECKERS`)
- Modify: `hooks/pre_push_gate.py` (add Python branch in `get_quality_commands`)
- Modify: `hooks/tests/test_util.py` (2 new detect_toolchain tests)
- Modify: `hooks/tests/test_file_checker.py` (5 new tests)
- Modify: `hooks/tests/test_pre_push_gate.py` (5 new tests)

---

- [ ] **Step 3.1: Write the failing tests**

**In `hooks/tests/test_util.py`**, add after existing `detect_toolchain` tests:

```python
def test_detect_python_toolchain_pyproject_toml(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]")
    kind, root = detect_toolchain(tmp_path)
    assert kind == ToolchainKind.PYTHON
    assert root == tmp_path


def test_detect_python_toolchain_setup_py(tmp_path):
    (tmp_path / "setup.py").write_text("from setuptools import setup")
    kind, root = detect_toolchain(tmp_path)
    assert kind == ToolchainKind.PYTHON
    assert root == tmp_path
```

Also add the import at top if `ToolchainKind` is not already imported:
```python
from _util import ToolchainKind, detect_toolchain, ...
```

**In `hooks/tests/test_file_checker.py`**, add at the bottom:

```python
import shutil
from unittest.mock import patch


def test_python_checker_calls_ruff_check_and_format(tmp_path, monkeypatch):
    """ruff check --fix and ruff format must both be called on a .py file."""
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ruff" if x == "ruff" else None)
    f = tmp_path / "main.py"
    f.write_text("x=1")

    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return 0, ""

    monkeypatch.setattr("file_checker.run_command", fake_run)
    from file_checker import _check_python
    _check_python(f, tmp_path)

    check_calls = [c for c in calls if "check" in c]
    format_calls = [c for c in calls if "format" in c]
    assert len(check_calls) == 1, f"Expected one ruff check call, got: {calls}"
    assert len(format_calls) == 1, f"Expected one ruff format call, got: {calls}"
    assert "--fix" in check_calls[0]


def test_python_checker_skips_when_ruff_not_installed(tmp_path, monkeypatch):
    """When ruff is not on PATH, return empty issues list silently."""
    monkeypatch.setattr(shutil, "which", lambda x: None)
    f = tmp_path / "main.py"
    f.write_text("x=1")
    from file_checker import _check_python
    issues = _check_python(f, tmp_path)
    assert issues == []


def test_python_checker_always_returns_no_issues(tmp_path, monkeypatch):
    """ruff runs silently — issues are fixed in place, not reported as issues."""
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ruff" if x == "ruff" else None)
    monkeypatch.setattr("file_checker.run_command", lambda *a, **kw: (1, "some error"))
    f = tmp_path / "main.py"
    f.write_text("x=1")
    from file_checker import _check_python
    issues = _check_python(f, tmp_path)
    assert issues == []


def test_python_checker_ruff_check_before_format(tmp_path, monkeypatch):
    """ruff check --fix must run before ruff format (fixes first, then formats)."""
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ruff" if x == "ruff" else None)
    f = tmp_path / "main.py"
    f.write_text("x=1")

    order = []
    def fake_run(cmd, **kwargs):
        if "check" in cmd:
            order.append("check")
        elif "format" in cmd:
            order.append("format")
        return 0, ""

    monkeypatch.setattr("file_checker.run_command", fake_run)
    from file_checker import _check_python
    _check_python(f, tmp_path)
    assert order == ["check", "format"], f"Expected check before format, got: {order}"


def test_non_python_toolchain_does_not_trigger_python_check(tmp_path, monkeypatch):
    """Python checker must not fire when toolchain is not PYTHON."""
    import file_checker
    from _util import ToolchainKind

    f = tmp_path / "server.go"
    f.write_text("package main")

    python_check_called = [False]
    original = file_checker._check_python
    def spy(*args, **kwargs):
        python_check_called[0] = True
        return []
    monkeypatch.setattr(file_checker, "_check_python", spy)
    monkeypatch.setattr("file_checker.detect_toolchain", lambda *a: (ToolchainKind.GO, tmp_path))
    monkeypatch.setattr("file_checker.load_devflow_config", lambda *a: {})
    monkeypatch.setattr("file_checker.read_hook_stdin",
                        lambda: {"tool_input": {"file_path": str(f)}})

    file_checker.main()
    assert not python_check_called[0]
```

**In `hooks/tests/test_pre_push_gate.py`**, add at the bottom:

```python
def test_quality_commands_python_returns_pytest(tmp_path, monkeypatch):
    """Python project must run pytest in pre-push gate."""
    monkeypatch.setattr(shutil, "which", lambda x: None)  # mypy not found
    cmds = get_quality_commands(ToolchainKind.PYTHON, tmp_path)
    assert len(cmds) >= 1
    pytest_cmd = cmds[0]
    assert pytest_cmd["label"] == "pytest"
    assert "python3" in pytest_cmd["cmd"]
    assert "-m" in pytest_cmd["cmd"]
    assert "pytest" in pytest_cmd["cmd"]


def test_quality_commands_python_pytest_flags(tmp_path, monkeypatch):
    """pytest must run with --tb=short -q for readable CI output."""
    monkeypatch.setattr(shutil, "which", lambda x: None)
    cmds = get_quality_commands(ToolchainKind.PYTHON, tmp_path)
    pytest_cmd = cmds[0]["cmd"]
    assert "--tb=short" in pytest_cmd
    assert "-q" in pytest_cmd


def test_quality_commands_python_includes_mypy_when_available(tmp_path, monkeypatch):
    """When mypy is on PATH, it must be added as a second check."""
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/mypy" if x == "mypy" else None)
    cmds = get_quality_commands(ToolchainKind.PYTHON, tmp_path)
    assert len(cmds) == 2
    assert cmds[1]["label"] == "mypy"
    assert "--ignore-missing-imports" in cmds[1]["cmd"]


def test_quality_commands_python_skips_mypy_gracefully(tmp_path, monkeypatch):
    """When mypy is not on PATH, exactly one command (pytest) is returned."""
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
```

Also add the import at top:
```python
import shutil
```
and
```python
from _util import ToolchainKind
```
(check these aren't already imported in the file)

- [ ] **Step 3.2: Run tests — verify all new tests FAIL**

```
python3.13 -m pytest hooks/tests/test_util.py hooks/tests/test_file_checker.py hooks/tests/test_pre_push_gate.py -q
```

Expected: 12 new tests FAIL (ToolchainKind.PYTHON doesn't exist yet), existing tests pass.

- [ ] **Step 3.3: Implement — add PYTHON to _util.py**

In `hooks/_util.py`:

1. Add `PYTHON = auto()` to `ToolchainKind`:

```python
class ToolchainKind(Enum):
    NODEJS = auto()
    FLUTTER = auto()
    MAVEN = auto()
    RUST = auto()
    GO = auto()
    PYTHON = auto()
```

2. Add Python fingerprints to `_TOOLCHAIN_FINGERPRINTS` (after `go.mod`):

```python
_TOOLCHAIN_FINGERPRINTS: list[tuple[str, ToolchainKind]] = [
    ("package.json", ToolchainKind.NODEJS),
    ("pubspec.yaml", ToolchainKind.FLUTTER),
    ("pom.xml", ToolchainKind.MAVEN),
    ("mvnw", ToolchainKind.MAVEN),
    ("Cargo.toml", ToolchainKind.RUST),
    ("go.mod", ToolchainKind.GO),
    ("pyproject.toml", ToolchainKind.PYTHON),
    ("setup.py", ToolchainKind.PYTHON),
]
```

- [ ] **Step 3.4: Run util tests — verify 2 new detect_toolchain tests pass**

```
python3.13 -m pytest hooks/tests/test_util.py -q
```

Expected: all util tests pass (2 new + existing).

- [ ] **Step 3.5: Implement — add _check_python to file_checker.py**

In `hooks/file_checker.py`:

1. Add the function after `_check_maven`:

```python
def _check_python(file_path: Path, project_root: Path) -> list[str]:
    ruff = shutil.which("ruff")
    if not ruff:
        return []
    run_command([ruff, "check", str(file_path), "--fix"], cwd=project_root)
    run_command([ruff, "format", str(file_path)], cwd=project_root)
    return []
```

2. Register it in `_CHECKERS`:

```python
_CHECKERS = {
    ToolchainKind.NODEJS: _check_nodejs,
    ToolchainKind.FLUTTER: _check_flutter,
    ToolchainKind.GO: _check_go,
    ToolchainKind.RUST: _check_rust,
    ToolchainKind.MAVEN: _check_maven,
    ToolchainKind.PYTHON: _check_python,
}
```

3. The `ToolchainKind` import at the top already includes the new `PYTHON` enum since it imports from `_util`.

- [ ] **Step 3.6: Run file_checker tests — verify 5 new tests pass**

```
python3.13 -m pytest hooks/tests/test_file_checker.py -q
```

Expected: all file_checker tests pass (5 new + 10 existing).

- [ ] **Step 3.7: Implement — add Python commands to pre_push_gate.py**

In `hooks/pre_push_gate.py`, add Python branch in `get_quality_commands()` after the `MAVEN` block:

```python
    if toolchain == ToolchainKind.PYTHON:
        cmds = [
            {
                "label": "pytest",
                "cmd": ["python3", "-m", "pytest", "--tb=short", "-q"],
                "timeout": 120,
            }
        ]
        if shutil.which("mypy"):
            cmds.append({
                "label": "mypy",
                "cmd": ["mypy", ".", "--ignore-missing-imports"],
                "timeout": 60,
            })
        return cmds
    return []
```

The existing `return []` at the end is replaced by the PYTHON block + final `return []`.

- [ ] **Step 3.8: Run pre_push_gate tests — verify 5 new tests pass**

```
python3.13 -m pytest hooks/tests/test_pre_push_gate.py -q
```

Expected: all pre_push_gate tests pass (5 new + 12 existing).

- [ ] **Step 3.9: Run full suite — no regressions**

```
python3.13 -m pytest hooks/tests/ -q
```

Expected: ≥320 passed.

---

## Task 4: Clean up state directory artefacts

### Context
Three empty directories exist in `~/.claude/devflow/state/` from test runs before STATE_ROOT patching was introduced: `hook-session-99`, `real-session-id`, `s1`. These tests are already correctly patched in `test_spec_phase_tracker.py` and generate no new artefacts. The stale directories just need to be deleted.

**Files:**
- Shell: `rm -rf ~/.claude/devflow/state/hook-session-99 ~/.claude/devflow/state/real-session-id ~/.claude/devflow/state/s1`

---

- [ ] **Step 4.1: Confirm artefacts exist**

```
ls ~/.claude/devflow/state/ | grep -E "hook-session-99|real-session|^s[0-9]+$"
```

Expected output (confirms artefacts present):
```
hook-session-99
real-session-id
s1
```

- [ ] **Step 4.2: Delete stale artefact directories**

```
rm -rf \
  ~/.claude/devflow/state/hook-session-99 \
  ~/.claude/devflow/state/real-session-id \
  ~/.claude/devflow/state/s1
```

- [ ] **Step 4.3: Run full test suite — verify no new artefacts created**

```
python3.13 -m pytest hooks/tests/ -q
```

- [ ] **Step 4.4: Verify state directory is clean**

```
ls ~/.claude/devflow/state/ | grep -E "hook-session-99|real-session|^s[0-9]+$"
```

Expected: empty output (no test artefacts).

---

## Task 5: Document in audit + final verification

**Files:**
- Modify: `docs/audit-20260331.md`

---

- [ ] **Step 5.1: Run the final test suite and capture count**

```
python3.13 -m pytest hooks/tests/ -q 2>&1 | tail -3
```

Note the exact test count from the output.

- [ ] **Step 5.2: Append to audit-20260331.md under ## Bug fixes**

Add this section after the existing "0B: discovery_scan" entry in `docs/audit-20260331.md`:

```markdown
### 0C: cross-session fix + pre_compact fix + Python toolchain + state cleanup (`2026-03-31`)

**Files changed:**
- `hooks/spec_stop_guard.py` — session ID bypass, COMPLETED file deletion, cwd ownership check
- `hooks/pre_compact.py` — `_find_active_spec()` reads `active-spec.json` instead of scanning `.md` files
- `hooks/_util.py` — `ToolchainKind.PYTHON` + `pyproject.toml` / `setup.py` fingerprints
- `hooks/file_checker.py` — `_check_python()`: ruff check --fix + ruff format, skip if not installed
- `hooks/pre_push_gate.py` — Python quality gate: pytest + optional mypy
- `hooks/tests/` — 4 obsolete pre_compact tests replaced, N new tests added

**Tests:** 292 → M total (N added, 4 removed)

**State cleanup:** deleted stale test artefact dirs `hook-session-99`, `real-session-id`, `s1` from `~/.claude/devflow/state/`.
```

Replace `M` and `N` with the actual counts from Step 5.1.

- [ ] **Step 5.3: Commit all changes**

```bash
cd /Users/vini/.claude/devflow
git add \
  hooks/spec_stop_guard.py \
  hooks/pre_compact.py \
  hooks/_util.py \
  hooks/file_checker.py \
  hooks/pre_push_gate.py \
  hooks/tests/test_spec_stop_guard.py \
  hooks/tests/test_compact_hooks.py \
  hooks/tests/test_file_checker.py \
  hooks/tests/test_pre_push_gate.py \
  hooks/tests/test_util.py \
  docs/audit-20260331.md \
  docs/plans/2026-03-31-0c-debt-fixes.md
git commit -m "fix(hooks): 0C — cross-session guard, pre_compact heuristic, Python toolchain, state cleanup"
```

---

## Self-Review Checklist

| Spec Requirement | Task |
|---|---|
| Fix 1a: empty/default session ID bypasses guard | Task 1, tests `test_empty_session_id_*`, `test_default_session_id_*` |
| Fix 1b: COMPLETED deletes active-spec.json | Task 1, tests `test_completed_spec_deletes_file`, `test_completed_spec_returns_not_active` |
| Fix 1c: cwd mismatch bypasses guard | Task 1, tests `test_cwd_mismatch_*`, `test_cwd_match_*`, `test_spec_without_cwd_*` |
| Fix 2: _find_active_spec reads state file | Task 2, 8 new tests |
| Fix 2: does not scan .md files | Task 2, `test_find_active_spec_does_not_scan_md_files` |
| Fix 3: ruff check + format on .py edit | Task 3, `test_python_checker_calls_ruff_*` |
| Fix 3: skip gracefully if ruff missing | Task 3, `test_python_checker_skips_when_ruff_not_installed` |
| Fix 3: pytest for Python project push | Task 3, `test_quality_commands_python_returns_pytest` |
| Fix 3: skip mypy gracefully | Task 3, `test_quality_commands_python_skips_mypy_gracefully` |
| Fix 3: non-Python files unaffected | Task 3, `test_non_python_toolchain_does_not_trigger_python_check` |
| Fix 4: state dir clean after test run | Task 4, Step 4.4 |
| Target ≥320 tests | Tasks 1–3 add 28 net tests: 292 - 4 + 32 = 320 |
| Document in audit-20260331.md | Task 5 |
