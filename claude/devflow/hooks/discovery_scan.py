"""
SessionStart hook — project discovery scan (devflow v2.2).
Detects: issue tracker, toolchain, design system, test framework.
Manages learned skill symlinks based on detected technologies.
Outputs project profile to context.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _util import ToolchainKind, detect_toolchain, get_state_dir, load_devflow_config

SKILLS_DIR = Path.home() / ".claude" / "skills"
LEARNED_SKILLS_DIR = Path.home() / ".claude" / "devflow" / "learned-skills"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


# ---------------------------------------------------------------------------
# Learned skill trigger functions: (project_root, cwd, toolchain) -> bool
# ---------------------------------------------------------------------------

def _has_docker(root: Path, cwd: Path, tc: Optional[ToolchainKind]) -> bool:
    return any(
        (root / f).exists()
        for f in ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"]
    )


def _has_icloud(root: Path, cwd: Path, tc: Optional[ToolchainKind]) -> bool:
    return "Mobile Documents/com~apple~CloudDocs" in str(cwd)


def _has_nextjs(root: Path, cwd: Path, tc: Optional[ToolchainKind]) -> bool:
    return any(
        (root / f).exists()
        for f in ["next.config.js", "next.config.ts", "next.config.mjs"]
    )


def _has_web_frontend(root: Path, cwd: Path, tc: Optional[ToolchainKind]) -> bool:
    if tc != ToolchainKind.NODEJS:
        return False
    return any((root / d).is_dir() for d in ["src", "app", "pages", "components"])


LEARNED_SKILL_TRIGGERS: dict[str, callable] = {
    "devflow-learned-docker-host-networking": _has_docker,
    "devflow-learned-icloud-rsync": _has_icloud,
    "devflow-learned-nextjs-standalone-native-modules": _has_nextjs,
    "devflow-learned-html5-video-autoplay": _has_web_frontend,
}


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def find_project_root(start: Path, max_levels: int = 6) -> Path:
    current = start
    for _ in range(max_levels):
        if (current / ".git").exists():
            return current
        for marker in ["pubspec.yaml", "package.json", "Cargo.toml", "go.mod", "pom.xml"]:
            if (current / marker).exists():
                return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start


def detect_issue_tracker(
    project_root: Path, settings: dict, config: dict,
) -> str:
    # 1. Explicit config override (highest priority)
    override = config.get("issue_tracker_override")
    if override:
        return override

    # 2. Project-level signals (per-repo markers beat global settings)
    github_dir = project_root / ".github"
    if (github_dir / "ISSUE_TEMPLATE").is_dir() or (github_dir / "issues.yml").exists():
        return "github_issues"

    for jira_marker in [".jira.yml", "atlassian.json"]:
        if (project_root / jira_marker).exists():
            return "jira"
    git_config = project_root / ".git" / "config"
    if git_config.exists():
        try:
            content = git_config.read_text()
            if "jira" in content.lower() or "atlassian" in content.lower():
                return "jira"
        except OSError:
            pass

    # 3. Global signals (Linear plugin/key in settings.json)
    plugins = settings.get("enabledPlugins", {})
    has_linear_plugin = any(
        "linear" in k.lower() for k in plugins if plugins.get(k)
    )
    has_linear_key = "linear" in settings
    if has_linear_plugin or has_linear_key:
        return "linear"

    # 4. Fallback file-based trackers
    for todo_marker in ["TODO.md", "BACKLOG.md"]:
        if (project_root / todo_marker).exists():
            return "todo_file"

    return "none"


def detect_design_system(project_root: Path) -> Optional[str]:
    patterns = [
        "packages/*design*system*",
        "packages/*ui*kit*",
        "src/design-system",
        "src/design_system",
        "lib/design-system",
        "lib/design_system",
    ]
    for pattern in patterns:
        for match in project_root.glob(pattern):
            if match.is_dir():
                try:
                    return str(match.relative_to(project_root))
                except ValueError:
                    return str(match)
    return None


def detect_test_framework(
    project_root: Path, toolchain: Optional[ToolchainKind],
) -> str:
    if toolchain == ToolchainKind.FLUTTER:
        return "flutter_test"
    if toolchain == ToolchainKind.GO:
        return "go_test"
    if toolchain == ToolchainKind.RUST:
        return "cargo_test"
    if toolchain == ToolchainKind.MAVEN:
        return "junit"
    if toolchain == ToolchainKind.NODEJS:
        pkg_json = project_root / "package.json"
        if pkg_json.exists():
            try:
                pkg = json.loads(pkg_json.read_text())
                deps = {
                    **pkg.get("devDependencies", {}),
                    **pkg.get("dependencies", {}),
                }
                for fw in ["vitest", "jest", "mocha", "ava", "tap"]:
                    if fw in deps:
                        return fw
            except (json.JSONDecodeError, OSError):
                pass
    return "unknown"


# ---------------------------------------------------------------------------
# Symlink management
# ---------------------------------------------------------------------------

def _ensure_learned_skills_dir() -> None:
    LEARNED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    for skill_name in LEARNED_SKILL_TRIGGERS:
        source = SKILLS_DIR / skill_name
        target = LEARNED_SKILLS_DIR / skill_name
        if target.is_dir():
            continue
        if source.is_dir() and not source.is_symlink():
            source.rename(target)


def _manage_symlinks(
    project_root: Path,
    cwd: Path,
    toolchain: Optional[ToolchainKind],
    config: dict,
) -> list[str]:
    if not config.get("learned_skills_auto_inject", True):
        return []

    injected: list[str] = []
    for skill_name, trigger_fn in LEARNED_SKILL_TRIGGERS.items():
        source = LEARNED_SKILLS_DIR / skill_name
        link = SKILLS_DIR / skill_name

        if not source.is_dir():
            continue

        should_link = trigger_fn(project_root, cwd, toolchain)

        if should_link and not link.exists():
            link.symlink_to(source)
        elif not should_link and link.is_symlink():
            link.unlink()

        if should_link:
            injected.append(skill_name)

    return injected


def _count_all_learned_skills() -> list[str]:
    """Return names of ALL installed learned skills (permanent + injected)."""
    installed = []
    if not SKILLS_DIR.is_dir():
        return installed
    for entry in SKILLS_DIR.iterdir():
        if entry.name.startswith("devflow-learned-") and entry.is_dir():
            installed.append(entry.name)
    return sorted(installed)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    cwd = Path.cwd()
    project_root = find_project_root(cwd)
    settings = _load_settings()

    toolchain, _ = detect_toolchain(project_root)
    in_project = (project_root != cwd) or any(
        (cwd / marker).exists()
        for marker in [".git", "package.json", "pubspec.yaml", "Cargo.toml", "go.mod", "pom.xml"]
    )
    config = load_devflow_config(project_root)

    issue_tracker = detect_issue_tracker(project_root, settings, config)
    design_system = detect_design_system(project_root)
    test_framework = detect_test_framework(project_root, toolchain)

    _ensure_learned_skills_dir()
    injected = _manage_symlinks(project_root, cwd, toolchain, config)

    tf_label = test_framework if in_project else "none"
    all_learned = _count_all_learned_skills()

    profile = {
        "project_root": str(project_root),
        "toolchain": toolchain.name if toolchain else (None if not in_project else "unknown"),
        "issue_tracker": issue_tracker,
        "design_system": design_system,
        "test_framework": tf_label,
        "injected_skills": injected,
        "all_learned_skills": all_learned,
        "in_project": in_project,
    }

    state_dir = get_state_dir()
    marker = state_dir / "discovery-ran"

    # Always remove stale marker first — if we crash before the end,
    # post_compact_restore will correctly inject the profile as fallback.
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass

    try:
        (state_dir / "project-profile.json").write_text(
            json.dumps(profile, indent=2),
        )
        marker.write_text("")
    except OSError:
        pass

    lines = ["[devflow:project-profile]"]
    lines.append(f"ISSUE_TRACKER_TYPE={issue_tracker}")
    if design_system:
        lines.append(f"DESIGN_SYSTEM_ROOT={design_system}")
    lines.append(f"TEST_FRAMEWORK={tf_label}")
    tc_label = toolchain.name if toolchain else ("none" if not in_project else "unknown")
    lines.append(f"TOOLCHAIN={tc_label}")
    if not in_project:
        lines.append("PROJECT=none (not in a project directory)")

    if all_learned:
        lines.append(f"LEARNED_SKILLS={','.join(all_learned)}")
    else:
        lines.append("LEARNED_SKILLS=none")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
