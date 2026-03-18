"""
PostToolUse hook (Write|Edit|MultiEdit) — language-agnostic quality checker.
Detects toolchain, runs format+lint, warns about file size.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import (
    GENERATED_PATTERNS,
    SKIP_DIRS,
    ToolchainKind,
    check_file_length,
    detect_toolchain,
    get_edited_file,
    hook_context,
    load_devflow_config,
    read_hook_stdin,
    run_command,
)

_SKIP_PATTERNS = {
    "test_", "_test.", ".test.", "_spec.", ".spec.",
    "conftest.", "fixture", "mock",
}
_SKIP_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".env", ".lock", ".gitignore",
}
_SKIP_NAMES = {"Dockerfile", "Makefile", "Procfile"}


def should_skip(file_path: Path) -> bool:
    name = file_path.name.lower()
    for part in file_path.parts:
        if part in SKIP_DIRS:
            return True
    if file_path.suffix.lower() in _SKIP_EXTENSIONS or name in {n.lower() for n in _SKIP_NAMES}:
        return True
    if any(name.endswith(pattern) for pattern in GENERATED_PATTERNS):
        return True
    if any(pattern in name for pattern in _SKIP_PATTERNS):
        return True
    return False


def get_length_message(file_path: Path, config: dict) -> str:
    warn_limit = config.get("file_length_warn", 400)
    critical_limit = config.get("file_length_critical", 600)
    warn, critical, lines = check_file_length(file_path, warn_limit, critical_limit)
    if not warn and not critical:
        return ""
    if critical:
        return (
            f"FILE TOO LONG: {file_path.name} has {lines} lines "
            f"(critical: {critical_limit}). Must split into smaller modules."
        )
    return (
        f"FILE GROWING: {file_path.name} has {lines} lines "
        f"(warn: {warn_limit}). Consider splitting."
    )


def _check_nodejs(file_path: Path, project_root: Path) -> list[str]:
    issues = []
    prettier = shutil.which("prettier")
    if not prettier:
        local = project_root / "node_modules" / ".bin" / "prettier"
        if local.exists():
            prettier = str(local)
    if prettier:
        code, output = run_command([prettier, "--write", str(file_path)], cwd=project_root)
        if code != 0 and output:
            issues.append(f"Prettier failed: {output[:300]}")
    eslint = shutil.which("eslint")
    if not eslint:
        local = project_root / "node_modules" / ".bin" / "eslint"
        if local.exists():
            eslint = str(local)
    if eslint:
        code, output = run_command([eslint, str(file_path)], cwd=project_root)
        if code != 0 and output:
            issues.append(f"ESLint: {output[:400]}")
    return issues


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


def _check_go(file_path: Path, project_root: Path) -> list[str]:
    issues = []
    if shutil.which("gofmt"):
        code, output = run_command(["gofmt", "-w", str(file_path)])
        if code != 0 and output:
            issues.append(f"gofmt failed: {output[:300]}")
    if shutil.which("go"):
        code, output = run_command(["go", "vet", str(file_path)], cwd=project_root)
        if code != 0 and output:
            issues.append(f"go vet: {output[:300]}")
    return issues


def _check_rust(file_path: Path, project_root: Path) -> list[str]:
    issues = []
    if shutil.which("cargo"):
        code, output = run_command(["cargo", "check"], cwd=project_root, timeout=60)
        if code != 0 and output:
            lines = [l for l in output.splitlines() if "error" in l.lower()][:5]
            if lines:
                issues.append("cargo check: " + "\n".join(lines))
    return issues


def _check_maven(file_path: Path, project_root: Path) -> list[str]:
    issues = []
    mvnw = project_root / "mvnw"
    mvn_cmd = str(mvnw) if mvnw.exists() else shutil.which("mvn")
    if not mvn_cmd:
        return issues
    if file_path.suffix == ".java":
        code, output = run_command([mvn_cmd, "compile", "-q"], cwd=project_root, timeout=60)
        if code != 0 and output:
            lines = [l for l in output.splitlines() if "ERROR" in l or "[ERROR]" in l][:5]
            if lines:
                issues.append("Maven compile: " + "\n".join(lines))
    return issues


_CHECKERS = {
    ToolchainKind.NODEJS: _check_nodejs,
    ToolchainKind.FLUTTER: _check_flutter,
    ToolchainKind.GO: _check_go,
    ToolchainKind.RUST: _check_rust,
    ToolchainKind.MAVEN: _check_maven,
}


def main() -> int:
    hook_data = read_hook_stdin()
    file_path = get_edited_file(hook_data)

    if not file_path or not file_path.exists():
        return 0

    if should_skip(file_path):
        return 0

    toolchain, project_root = detect_toolchain(file_path.parent)
    config = load_devflow_config(project_root)
    length_msg = get_length_message(file_path, config)

    issues: list[str] = []

    if toolchain and toolchain in _CHECKERS:
        root = project_root or file_path.parent
        issues = _CHECKERS[toolchain](file_path, root)

    if issues or length_msg:
        parts = []
        if issues:
            parts.extend(issues)
        if length_msg:
            parts.append(length_msg)
        context = "\n".join(parts)
        print(hook_context(f"[devflow quality]\n{context}"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
