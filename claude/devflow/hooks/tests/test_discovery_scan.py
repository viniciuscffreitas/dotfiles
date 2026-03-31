"""
Tests for hooks/discovery_scan.py.

All tests use tmp_path — never write to ~/.claude/devflow/state/.
Module-level constants (SKILLS_DIR, LEARNED_SKILLS_DIR, SETTINGS_PATH)
are patched where needed to prevent side effects on the real filesystem.

Coverage target: >= 80% line coverage.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from _util import ToolchainKind
from discovery_scan import (
    _count_all_learned_skills,
    _ensure_learned_skills_dir,
    _has_docker,
    _has_icloud,
    _has_nextjs,
    _has_web_frontend,
    _load_settings,
    _manage_symlinks,
    detect_design_system,
    detect_issue_tracker,
    detect_test_framework,
    find_project_root,
    main,
)


# ---------------------------------------------------------------------------
# Fixture: run_main
# Runs main() with all external I/O patched so tests stay in tmp_path.
# ---------------------------------------------------------------------------

@pytest.fixture
def run_main(tmp_path, monkeypatch):
    """Return a helper that runs main() with standard external deps patched."""
    _default_config = {
        "file_length_warn": 400,
        "file_length_critical": 600,
        "learned_skills_auto_inject": True,
        "issue_tracker_override": None,
    }

    def _run(project_root=None, settings=None, learned_skills=None, manage_returns=None):
        root = project_root or tmp_path
        state_dir = tmp_path / "state"
        state_dir.mkdir(exist_ok=True)
        monkeypatch.chdir(root)

        with patch("discovery_scan.get_state_dir", return_value=state_dir), \
             patch("discovery_scan._load_settings", return_value=settings or {}), \
             patch("discovery_scan.load_devflow_config", return_value=_default_config), \
             patch("discovery_scan._ensure_learned_skills_dir"), \
             patch("discovery_scan._manage_symlinks", return_value=manage_returns or []), \
             patch("discovery_scan._count_all_learned_skills", return_value=learned_skills or []):
            rc = main()

        profile_path = state_dir / "project-profile.json"
        profile = json.loads(profile_path.read_text()) if profile_path.exists() else None
        return rc, state_dir, profile

    return _run


# ---------------------------------------------------------------------------
# find_project_root
# ---------------------------------------------------------------------------

def test_find_project_root_with_git_dir(tmp_path):
    (tmp_path / ".git").mkdir()
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_with_package_json(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_with_pubspec_yaml(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: app")
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_with_cargo_toml(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = \"app\"\n")
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_walks_up_to_git(tmp_path):
    (tmp_path / ".git").mkdir()
    child = tmp_path / "lib" / "src"
    child.mkdir(parents=True)
    assert find_project_root(child) == tmp_path


def test_find_project_root_no_marker_returns_start(tmp_path):
    child = tmp_path / "sub"
    child.mkdir()
    # max_levels=2 keeps us within tmp_path; no marker → returns start
    result = find_project_root(child, max_levels=2)
    assert result == child


def test_find_project_root_symlinked_root(tmp_path):
    real = tmp_path / "real_project"
    real.mkdir()
    (real / "package.json").write_text("{}")
    link = tmp_path / "linked_project"
    link.symlink_to(real)
    # Should find the marker through the symlink
    result = find_project_root(link)
    assert result == link


# ---------------------------------------------------------------------------
# detect_issue_tracker
# ---------------------------------------------------------------------------

def test_detect_issue_tracker_config_override(tmp_path):
    result = detect_issue_tracker(tmp_path, {}, {"issue_tracker_override": "jira"})
    assert result == "jira"


def test_detect_issue_tracker_config_override_beats_github(tmp_path):
    (tmp_path / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True)
    result = detect_issue_tracker(tmp_path, {}, {"issue_tracker_override": "linear"})
    assert result == "linear"


def test_detect_issue_tracker_github_issue_template_dir(tmp_path):
    (tmp_path / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True)
    assert detect_issue_tracker(tmp_path, {}, {}) == "github_issues"


def test_detect_issue_tracker_github_issues_yml(tmp_path):
    github = tmp_path / ".github"
    github.mkdir()
    (github / "issues.yml").write_text("blank_issues_enabled: false\n")
    assert detect_issue_tracker(tmp_path, {}, {}) == "github_issues"


def test_detect_issue_tracker_jira_marker_file(tmp_path):
    (tmp_path / ".jira.yml").write_text("project: FOO\n")
    assert detect_issue_tracker(tmp_path, {}, {}) == "jira"


def test_detect_issue_tracker_atlassian_json(tmp_path):
    (tmp_path / "atlassian.json").write_text("{}\n")
    assert detect_issue_tracker(tmp_path, {}, {}) == "jira"


def test_detect_issue_tracker_jira_in_git_config(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text("[remote]\n  url = https://company.atlassian.net/repo\n")
    assert detect_issue_tracker(tmp_path, {}, {}) == "jira"


def test_detect_issue_tracker_git_config_read_oserror(tmp_path):
    """OSError reading .git/config is silently caught — no crash."""
    git = tmp_path / ".git"
    git.mkdir()
    cfg = git / "config"
    cfg.write_text("[core]\n  repositoryformatversion = 0\n")

    original = Path.read_text

    def selective_fail(self, *args, **kwargs):
        if self == cfg:
            raise OSError("permission denied")
        return original(self, *args, **kwargs)

    with patch.object(Path, "read_text", selective_fail):
        result = detect_issue_tracker(tmp_path, {}, {})

    assert isinstance(result, str)  # no crash; graceful fallback


def test_detect_issue_tracker_linear_plugin_in_settings(tmp_path):
    settings = {"enabledPlugins": {"plugin_linear_linear": True}}
    assert detect_issue_tracker(tmp_path, settings, {}) == "linear"


def test_detect_issue_tracker_linear_key_in_settings(tmp_path):
    settings = {"linear": {"apiKey": "lin_xxx"}}
    assert detect_issue_tracker(tmp_path, settings, {}) == "linear"


def test_detect_issue_tracker_todo_md(tmp_path):
    (tmp_path / "TODO.md").write_text("# Todo\n")
    assert detect_issue_tracker(tmp_path, {}, {}) == "todo_file"


def test_detect_issue_tracker_backlog_md(tmp_path):
    (tmp_path / "BACKLOG.md").write_text("# Backlog\n")
    assert detect_issue_tracker(tmp_path, {}, {}) == "todo_file"


def test_detect_issue_tracker_none_when_no_signals(tmp_path):
    assert detect_issue_tracker(tmp_path, {}, {}) == "none"


# ---------------------------------------------------------------------------
# detect_design_system
# ---------------------------------------------------------------------------

def test_detect_design_system_returns_none_by_default(tmp_path):
    assert detect_design_system(tmp_path) is None


def test_detect_design_system_src_design_system(tmp_path):
    (tmp_path / "src" / "design-system").mkdir(parents=True)
    assert detect_design_system(tmp_path) == "src/design-system"


def test_detect_design_system_src_design_system_underscore(tmp_path):
    (tmp_path / "src" / "design_system").mkdir(parents=True)
    assert detect_design_system(tmp_path) == "src/design_system"


def test_detect_design_system_lib_design_system(tmp_path):
    (tmp_path / "lib" / "design-system").mkdir(parents=True)
    assert detect_design_system(tmp_path) == "lib/design-system"


def test_detect_design_system_lib_design_system_underscore(tmp_path):
    (tmp_path / "lib" / "design_system").mkdir(parents=True)
    assert detect_design_system(tmp_path) == "lib/design_system"


def test_detect_design_system_packages_glob(tmp_path):
    ds = tmp_path / "packages" / "my-design-system-tokens"
    ds.mkdir(parents=True)
    result = detect_design_system(tmp_path)
    assert result == "packages/my-design-system-tokens"


def test_detect_design_system_packages_ui_kit(tmp_path):
    (tmp_path / "packages" / "my-ui-kit").mkdir(parents=True)
    assert detect_design_system(tmp_path) == "packages/my-ui-kit"


# ---------------------------------------------------------------------------
# detect_test_framework
# ---------------------------------------------------------------------------

def test_detect_test_framework_flutter(tmp_path):
    assert detect_test_framework(tmp_path, ToolchainKind.FLUTTER) == "flutter_test"


def test_detect_test_framework_go(tmp_path):
    assert detect_test_framework(tmp_path, ToolchainKind.GO) == "go_test"


def test_detect_test_framework_rust(tmp_path):
    assert detect_test_framework(tmp_path, ToolchainKind.RUST) == "cargo_test"


def test_detect_test_framework_maven(tmp_path):
    assert detect_test_framework(tmp_path, ToolchainKind.MAVEN) == "junit"


def test_detect_test_framework_nodejs_vitest(tmp_path):
    pkg = {"devDependencies": {"vitest": "^1.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    assert detect_test_framework(tmp_path, ToolchainKind.NODEJS) == "vitest"


def test_detect_test_framework_nodejs_jest(tmp_path):
    pkg = {"devDependencies": {"jest": "^29.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    assert detect_test_framework(tmp_path, ToolchainKind.NODEJS) == "jest"


def test_detect_test_framework_nodejs_mocha(tmp_path):
    pkg = {"dependencies": {"mocha": "^10.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    assert detect_test_framework(tmp_path, ToolchainKind.NODEJS) == "mocha"


def test_detect_test_framework_nodejs_vitest_beats_jest(tmp_path):
    """vitest comes first in the priority list."""
    pkg = {"devDependencies": {"vitest": "^1.0.0", "jest": "^29.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    assert detect_test_framework(tmp_path, ToolchainKind.NODEJS) == "vitest"


def test_detect_test_framework_nodejs_no_known_framework(tmp_path):
    pkg = {"dependencies": {"express": "^4.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    assert detect_test_framework(tmp_path, ToolchainKind.NODEJS) == "unknown"


def test_detect_test_framework_nodejs_invalid_json(tmp_path):
    (tmp_path / "package.json").write_text("{not valid json")
    assert detect_test_framework(tmp_path, ToolchainKind.NODEJS) == "unknown"


def test_detect_test_framework_nodejs_oserror_on_read(tmp_path):
    """OSError reading package.json is caught — returns 'unknown'."""
    pkg_path = tmp_path / "package.json"
    pkg_path.write_text("{}")

    original = Path.read_text

    def fail_for_pkg(self, *args, **kwargs):
        if self == pkg_path:
            raise OSError("permission denied")
        return original(self, *args, **kwargs)

    with patch.object(Path, "read_text", fail_for_pkg):
        result = detect_test_framework(tmp_path, ToolchainKind.NODEJS)

    assert result == "unknown"


def test_detect_test_framework_none_toolchain(tmp_path):
    assert detect_test_framework(tmp_path, None) == "unknown"


# ---------------------------------------------------------------------------
# _load_settings
# ---------------------------------------------------------------------------

def test_load_settings_missing_file_returns_empty():
    with patch("discovery_scan.SETTINGS_PATH", Path("/nonexistent/__settings.json")):
        assert _load_settings() == {}


def test_load_settings_invalid_json_returns_empty(tmp_path):
    bad = tmp_path / "settings.json"
    bad.write_text("{not json")
    with patch("discovery_scan.SETTINGS_PATH", bad):
        assert _load_settings() == {}


def test_load_settings_valid_json_returned(tmp_path):
    cfg = {"enabledPlugins": {"linear-mcp": True}}
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(cfg))
    with patch("discovery_scan.SETTINGS_PATH", f):
        assert _load_settings() == cfg


# ---------------------------------------------------------------------------
# Learned skill trigger functions
# ---------------------------------------------------------------------------

def test_has_docker_with_dockerfile(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM ubuntu\n")
    assert _has_docker(tmp_path, tmp_path, None) is True


def test_has_docker_with_compose_yml(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
    assert _has_docker(tmp_path, tmp_path, None) is True


def test_has_docker_with_compose_yaml(tmp_path):
    (tmp_path / "docker-compose.yaml").write_text("version: '3'\n")
    assert _has_docker(tmp_path, tmp_path, None) is True


def test_has_docker_no_docker_files(tmp_path):
    assert _has_docker(tmp_path, tmp_path, None) is False


def test_has_icloud_when_cwd_is_in_icloud(tmp_path):
    icloud = Path("/Users/vini/Library/Mobile Documents/com~apple~CloudDocs/project")
    assert _has_icloud(tmp_path, icloud, None) is True


def test_has_icloud_when_cwd_is_not_icloud(tmp_path):
    assert _has_icloud(tmp_path, tmp_path, None) is False


def test_has_nextjs_config_js(tmp_path):
    (tmp_path / "next.config.js").write_text("module.exports = {}\n")
    assert _has_nextjs(tmp_path, tmp_path, None) is True


def test_has_nextjs_config_ts(tmp_path):
    (tmp_path / "next.config.ts").write_text("export default {}\n")
    assert _has_nextjs(tmp_path, tmp_path, None) is True


def test_has_nextjs_config_mjs(tmp_path):
    (tmp_path / "next.config.mjs").write_text("export default {}\n")
    assert _has_nextjs(tmp_path, tmp_path, None) is True


def test_has_nextjs_no_config(tmp_path):
    assert _has_nextjs(tmp_path, tmp_path, None) is False


def test_has_web_frontend_nodejs_with_src_dir(tmp_path):
    (tmp_path / "src").mkdir()
    assert _has_web_frontend(tmp_path, tmp_path, ToolchainKind.NODEJS) is True


def test_has_web_frontend_nodejs_with_app_dir(tmp_path):
    (tmp_path / "app").mkdir()
    assert _has_web_frontend(tmp_path, tmp_path, ToolchainKind.NODEJS) is True


def test_has_web_frontend_nodejs_with_pages_dir(tmp_path):
    (tmp_path / "pages").mkdir()
    assert _has_web_frontend(tmp_path, tmp_path, ToolchainKind.NODEJS) is True


def test_has_web_frontend_nodejs_with_components_dir(tmp_path):
    (tmp_path / "components").mkdir()
    assert _has_web_frontend(tmp_path, tmp_path, ToolchainKind.NODEJS) is True


def test_has_web_frontend_flutter_not_detected(tmp_path):
    (tmp_path / "src").mkdir()
    assert _has_web_frontend(tmp_path, tmp_path, ToolchainKind.FLUTTER) is False


def test_has_web_frontend_nodejs_no_frontend_dirs(tmp_path):
    assert _has_web_frontend(tmp_path, tmp_path, ToolchainKind.NODEJS) is False


# ---------------------------------------------------------------------------
# _count_all_learned_skills
# ---------------------------------------------------------------------------

def test_count_all_learned_skills_empty_dir(tmp_path):
    with patch("discovery_scan.SKILLS_DIR", tmp_path):
        assert _count_all_learned_skills() == []


def test_count_all_learned_skills_finds_learned_dirs(tmp_path):
    (tmp_path / "devflow-learned-docker").mkdir()
    (tmp_path / "devflow-learned-nextjs").mkdir()
    (tmp_path / "other-skill").mkdir()  # excluded: no devflow-learned- prefix
    with patch("discovery_scan.SKILLS_DIR", tmp_path):
        result = _count_all_learned_skills()
    assert result == ["devflow-learned-docker", "devflow-learned-nextjs"]


def test_count_all_learned_skills_dir_missing(tmp_path):
    nonexistent = tmp_path / "missing"
    with patch("discovery_scan.SKILLS_DIR", nonexistent):
        assert _count_all_learned_skills() == []


def test_count_all_learned_skills_sorted(tmp_path):
    (tmp_path / "devflow-learned-zzz").mkdir()
    (tmp_path / "devflow-learned-aaa").mkdir()
    with patch("discovery_scan.SKILLS_DIR", tmp_path):
        result = _count_all_learned_skills()
    assert result == ["devflow-learned-aaa", "devflow-learned-zzz"]


# ---------------------------------------------------------------------------
# _manage_symlinks
# ---------------------------------------------------------------------------

def test_manage_symlinks_auto_inject_disabled_returns_empty(tmp_path):
    result = _manage_symlinks(tmp_path, tmp_path, ToolchainKind.NODEJS, {"learned_skills_auto_inject": False})
    assert result == []


def test_manage_symlinks_injects_skill_when_trigger_matches(tmp_path):
    learned = tmp_path / "learned-skills"
    skills = tmp_path / "skills"
    skills.mkdir()
    docker_source = learned / "devflow-learned-docker-host-networking"
    docker_source.mkdir(parents=True)
    (tmp_path / "Dockerfile").write_text("FROM ubuntu\n")

    with patch("discovery_scan.LEARNED_SKILLS_DIR", learned), \
         patch("discovery_scan.SKILLS_DIR", skills):
        result = _manage_symlinks(tmp_path, tmp_path, None, {"learned_skills_auto_inject": True})

    assert "devflow-learned-docker-host-networking" in result
    link = skills / "devflow-learned-docker-host-networking"
    assert link.is_symlink()


def test_manage_symlinks_removes_stale_link_when_trigger_no_longer_matches(tmp_path):
    learned = tmp_path / "learned-skills"
    skills = tmp_path / "skills"
    skills.mkdir()
    docker_source = learned / "devflow-learned-docker-host-networking"
    docker_source.mkdir(parents=True)
    # Pre-existing symlink, but no Dockerfile in project → trigger=False
    link = skills / "devflow-learned-docker-host-networking"
    link.symlink_to(docker_source)
    assert link.exists()

    with patch("discovery_scan.LEARNED_SKILLS_DIR", learned), \
         patch("discovery_scan.SKILLS_DIR", skills):
        result = _manage_symlinks(tmp_path, tmp_path, None, {"learned_skills_auto_inject": True})

    assert "devflow-learned-docker-host-networking" not in result
    assert not link.exists()


# ---------------------------------------------------------------------------
# main() — output contract
# ---------------------------------------------------------------------------

def test_main_returns_zero(run_main):
    rc, _, _ = run_main()
    assert rc == 0


def test_main_writes_profile_json(run_main, tmp_path):
    _, state_dir, _ = run_main()
    assert (state_dir / "project-profile.json").exists()


def test_main_profile_is_valid_json(run_main):
    _, state_dir, profile = run_main()
    assert profile is not None
    assert isinstance(profile, dict)


def test_main_profile_has_all_required_fields(run_main):
    """All fields read by post_compact_restore and pre_compact must be present."""
    _, _, profile = run_main()
    required = [
        "project_root", "toolchain", "issue_tracker", "design_system",
        "test_framework", "injected_skills", "all_learned_skills", "in_project",
    ]
    for field in required:
        assert field in profile, f"Required field missing from profile: {field}"


def test_main_creates_discovery_ran_marker(run_main, tmp_path):
    _, state_dir, _ = run_main()
    assert (state_dir / "discovery-ran").exists()


def test_main_stdout_has_profile_header(run_main, capsys):
    run_main()
    out = capsys.readouterr().out
    assert "[devflow:project-profile]" in out
    assert "ISSUE_TRACKER_TYPE=" in out
    assert "TEST_FRAMEWORK=" in out
    assert "TOOLCHAIN=" in out


def test_main_stdout_has_learned_skills_line(run_main, capsys):
    run_main(learned_skills=["devflow-learned-docker"])
    out = capsys.readouterr().out
    assert "LEARNED_SKILLS=devflow-learned-docker" in out


def test_main_stdout_learned_skills_none_when_empty(run_main, capsys):
    run_main(learned_skills=[])
    out = capsys.readouterr().out
    assert "LEARNED_SKILLS=none" in out


# ---------------------------------------------------------------------------
# main() — toolchain detection integration
# ---------------------------------------------------------------------------

def test_main_detects_flutter_project(run_main, tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: myapp\n")
    _, _, profile = run_main()
    assert profile["toolchain"] == "FLUTTER"
    assert profile["test_framework"] == "flutter_test"
    assert profile["in_project"] is True


def test_main_detects_nodejs_project_with_jest(run_main, tmp_path):
    pkg = {"name": "myapp", "devDependencies": {"jest": "^29.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    _, _, profile = run_main()
    assert profile["toolchain"] == "NODEJS"
    assert profile["test_framework"] == "jest"
    assert profile["in_project"] is True


def test_main_detects_rust_project(run_main, tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = \"myapp\"\n")
    _, _, profile = run_main()
    assert profile["toolchain"] == "RUST"
    assert profile["test_framework"] == "cargo_test"
    assert profile["in_project"] is True


def test_main_detects_go_project(run_main, tmp_path):
    (tmp_path / "go.mod").write_text("module github.com/foo\n\ngo 1.21\n")
    _, _, profile = run_main()
    assert profile["toolchain"] == "GO"
    assert profile["test_framework"] == "go_test"
    assert profile["in_project"] is True


def test_main_unknown_project_sets_not_in_project(run_main):
    """Empty dir with no markers → in_project=False, toolchain=None."""
    rc, _, profile = run_main()
    assert rc == 0
    assert profile["in_project"] is False


# ---------------------------------------------------------------------------
# main() — idempotency
# ---------------------------------------------------------------------------

def test_main_idempotent(tmp_path, monkeypatch):
    """Running main() twice on the same project produces identical profiles."""
    (tmp_path / "pubspec.yaml").write_text("name: myapp\n")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    _default_config = {
        "file_length_warn": 400,
        "file_length_critical": 600,
        "learned_skills_auto_inject": True,
        "issue_tracker_override": None,
    }

    def _run():
        with patch("discovery_scan.get_state_dir", return_value=state_dir), \
             patch("discovery_scan._load_settings", return_value={}), \
             patch("discovery_scan.load_devflow_config", return_value=_default_config), \
             patch("discovery_scan._ensure_learned_skills_dir"), \
             patch("discovery_scan._manage_symlinks", return_value=[]), \
             patch("discovery_scan._count_all_learned_skills", return_value=[]):
            main()

    _run()
    profile1 = json.loads((state_dir / "project-profile.json").read_text())
    _run()
    profile2 = json.loads((state_dir / "project-profile.json").read_text())

    assert profile1 == profile2


# ---------------------------------------------------------------------------
# Python & TypeScript — explicit behavior documentation
# (These are NOT bugs — they document the current design of _util.detect_toolchain)
# ---------------------------------------------------------------------------

def test_python_pyproject_toml_not_in_fingerprints(tmp_path):
    """pyproject.toml is a Python fingerprint — detect_toolchain returns PYTHON."""
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = \"app\"\n")
    from _util import detect_toolchain, ToolchainKind
    tc, _ = detect_toolchain(tmp_path)
    assert tc == ToolchainKind.PYTHON


def test_python_setup_py_not_in_fingerprints(tmp_path):
    """setup.py is a recognized Python fingerprint."""
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")
    from _util import detect_toolchain, ToolchainKind
    tc, _ = detect_toolchain(tmp_path)
    assert tc == ToolchainKind.PYTHON


def test_typescript_uses_nodejs_toolchain(tmp_path):
    """TypeScript projects have package.json, which maps to NODEJS.
    tsconfig.json alone is not a fingerprint.
    """
    (tmp_path / "package.json").write_text('{"name": "myapp"}')
    (tmp_path / "tsconfig.json").write_text("{}")
    from _util import detect_toolchain
    tc, _ = detect_toolchain(tmp_path)
    assert tc == ToolchainKind.NODEJS


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_main_empty_directory_no_crash(run_main):
    rc, state_dir, profile = run_main()
    assert rc == 0
    assert profile is not None


def test_main_hidden_files_only_no_crash(run_main, tmp_path):
    (tmp_path / ".hidden").write_text("secret")
    (tmp_path / ".env").write_text("KEY=value")
    rc, _, profile = run_main()
    assert rc == 0
    assert profile is not None


def test_main_oserror_on_profile_write_does_not_raise(tmp_path, monkeypatch):
    """If writing project-profile.json fails with OSError, main() still returns 0."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    _default_config = {
        "file_length_warn": 400,
        "file_length_critical": 600,
        "learned_skills_auto_inject": True,
        "issue_tracker_override": None,
    }
    original_write_text = Path.write_text

    def fail_for_state_files(self, *args, **kwargs):
        if str(self).startswith(str(state_dir)):
            raise OSError("read-only filesystem")
        return original_write_text(self, *args, **kwargs)

    with patch("discovery_scan.get_state_dir", return_value=state_dir), \
         patch("discovery_scan._load_settings", return_value={}), \
         patch("discovery_scan.load_devflow_config", return_value=_default_config), \
         patch("discovery_scan._ensure_learned_skills_dir"), \
         patch("discovery_scan._manage_symlinks", return_value=[]), \
         patch("discovery_scan._count_all_learned_skills", return_value=[]), \
         patch.object(Path, "write_text", fail_for_state_files):
        rc = main()

    assert rc == 0


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def test_main_performance_500_files_under_3s(run_main, tmp_path):
    """Scanning a flat directory of 500+ files must complete in < 3 seconds."""
    for i in range(500):
        (tmp_path / f"file_{i:04d}.txt").write_text(f"content {i}\n")

    t0 = time.perf_counter()
    rc, _, _ = run_main()
    elapsed = time.perf_counter() - t0

    assert rc == 0
    assert elapsed < 3.0, f"main() took {elapsed:.2f}s with 500 files (limit: 3.0s)"


# ---------------------------------------------------------------------------
# _ensure_learned_skills_dir  (line 179-186)
# ---------------------------------------------------------------------------

def test_ensure_learned_skills_dir_creates_dir_and_skips_existing(tmp_path):
    """_ensure_learned_skills_dir creates LEARNED_SKILLS_DIR and skips skills
    whose target already exists."""
    learned = tmp_path / "learned-skills"
    skills = tmp_path / "skills"
    skills.mkdir()

    # Pre-create target for one trigger skill → should be skipped (continue)
    trigger_skill = next(iter(__import__("discovery_scan").LEARNED_SKILL_TRIGGERS))
    (learned / trigger_skill).mkdir(parents=True)

    with patch("discovery_scan.LEARNED_SKILLS_DIR", learned), \
         patch("discovery_scan.SKILLS_DIR", skills):
        _ensure_learned_skills_dir()

    assert learned.is_dir()


def test_ensure_learned_skills_dir_renames_source_to_target(tmp_path):
    """If SKILLS_DIR has a real (non-symlink) skill dir, it is moved to LEARNED_SKILLS_DIR."""
    import discovery_scan as ds
    learned = tmp_path / "learned-skills"
    skills = tmp_path / "skills"
    skills.mkdir()

    trigger_skill = next(iter(ds.LEARNED_SKILL_TRIGGERS))
    source = skills / trigger_skill
    source.mkdir()

    with patch("discovery_scan.LEARNED_SKILLS_DIR", learned), \
         patch("discovery_scan.SKILLS_DIR", skills):
        _ensure_learned_skills_dir()

    assert not source.exists()
    assert (learned / trigger_skill).is_dir()


# ---------------------------------------------------------------------------
# main() — DESIGN_SYSTEM_ROOT in stdout  (line 288)
# ---------------------------------------------------------------------------

def test_main_stdout_includes_design_system_root(run_main, tmp_path, capsys):
    """When a design system dir is detected, stdout includes DESIGN_SYSTEM_ROOT=."""
    (tmp_path / "src" / "design-system").mkdir(parents=True)
    run_main()
    out = capsys.readouterr().out
    assert "DESIGN_SYSTEM_ROOT=src/design-system" in out
