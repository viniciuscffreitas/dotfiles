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

sys.path.insert(0, str(Path(__file__).parent.parent))
from linters.engine import LinterEngine

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
                "cmd": ["flutter", "analyze", "--no-fatal-infos"],
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
                    cmds.append({"label": "npm lint", "cmd": ["npm", "run", "lint"], "timeout": 60})
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


def get_diff(project_root: Path) -> str:
    """Get diff for linters. Tries HEAD~1 first, falls back to unstaged diff."""
    code, output = run_command(["git", "diff", "HEAD~1"], cwd=project_root, timeout=10)
    if code == 0 and output.strip():
        return output
    code, output = run_command(["git", "diff"], cwd=project_root, timeout=10)
    return output if code == 0 else ""


def run_linters(diff: str, project_root: Path) -> bool:
    """Run all linters. Prints summary line. Returns True if all pass."""
    engine = LinterEngine()
    results = engine.run_all(diff, project_root)
    parts = []
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        parts.append(f"{r.linter_name}: {status}")
        for v in r.violations:
            print(f"  [devflow:lint] {v}")
    print(f"[devflow:lint] {' | '.join(parts)}")
    return all(r.passed for r in results)


def main() -> int:
    hook_data = read_hook_stdin()
    command = get_bash_command(hook_data)

    if not should_gate(command):
        return 0

    toolchain, project_root = detect_toolchain(Path.cwd())
    if not toolchain or not project_root:
        return 0

    # --- Deterministic linters (run first, cheap, never hallucinate) ---
    diff = get_diff(project_root)
    if not run_linters(diff, project_root):
        msg = "Pre-push gate BLOCKED: linter violations found (see above).\n"
        print(hook_block(msg))
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
