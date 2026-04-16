"""
Tests for install_skills.py — verifies cross-platform skill linking.

Bug fix: install.sh used bash 'ln -s' which fails on Windows without Developer
Mode or admin privileges. Fix: Python-based symlink with fallback to
shutil.copytree when symlink creation fails (OSError).
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_DEVFLOW_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))


def _load_module():
    import install_skills
    importlib.reload(install_skills)
    return install_skills


class TestSkillLinkingSymlink:
    """Contract: when os.symlink succeeds, creates a symlink."""

    def test_creates_symlink_when_allowed(self, tmp_path):
        m = _load_module()
        # Create a fake skill dir
        devflow_dir = tmp_path / "devflow"
        skill_src = devflow_dir / "skills" / "devflow-test-skill"
        skill_src.mkdir(parents=True)
        (skill_src / "SKILL.md").write_text("# test")

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        m.link_skills(devflow_dir, skills_dir)

        target = skills_dir / "devflow-test-skill"
        assert target.exists(), "skill target must exist"
        assert target.is_symlink() or target.is_dir(), "target must be symlink or dir"

    def test_symlink_target_points_to_source(self, tmp_path):
        m = _load_module()
        devflow_dir = tmp_path / "devflow"
        skill_src = devflow_dir / "skills" / "devflow-myskill"
        skill_src.mkdir(parents=True)
        (skill_src / "SKILL.md").write_text("content")

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        with patch("os.symlink") as mock_symlink:
            m.link_skills(devflow_dir, skills_dir)
            mock_symlink.assert_called_once()
            src_arg, dst_arg = mock_symlink.call_args[0]
            assert "devflow-myskill" in str(src_arg)
            assert "devflow-myskill" in str(dst_arg)


class TestSkillLinkingFallback:
    """Contract: when os.symlink raises OSError, falls back to shutil.copytree."""

    def test_falls_back_to_copytree_on_symlink_error(self, tmp_path):
        m = _load_module()
        devflow_dir = tmp_path / "devflow"
        skill_src = devflow_dir / "skills" / "devflow-fallback-skill"
        skill_src.mkdir(parents=True)
        (skill_src / "SKILL.md").write_text("# fallback test")

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        with patch("os.symlink", side_effect=OSError("symlink not permitted")), \
             patch("shutil.copytree") as mock_copy:
            m.link_skills(devflow_dir, skills_dir)
            mock_copy.assert_called_once()
            src_arg = str(mock_copy.call_args[0][0])
            dst_arg = str(mock_copy.call_args[0][1])
            assert "devflow-fallback-skill" in src_arg
            assert "devflow-fallback-skill" in dst_arg

    def test_fallback_result_is_accessible_directory(self, tmp_path):
        m = _load_module()
        devflow_dir = tmp_path / "devflow"
        skill_src = devflow_dir / "skills" / "devflow-copy-skill"
        skill_src.mkdir(parents=True)
        (skill_src / "SKILL.md").write_text("# copy fallback")

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        with patch("os.symlink", side_effect=OSError("no symlinks on Windows")):
            m.link_skills(devflow_dir, skills_dir)

        target = skills_dir / "devflow-copy-skill"
        assert target.exists() and target.is_dir(), "fallback copy must produce a directory"
        assert (target / "SKILL.md").read_text() == "# copy fallback"


class TestSkillLinkingExisting:
    """Contract: existing symlinks are replaced; existing real directories are skipped."""

    def test_existing_symlink_is_replaced(self, tmp_path):
        m = _load_module()
        devflow_dir = tmp_path / "devflow"
        skill_src = devflow_dir / "skills" / "devflow-replace-skill"
        skill_src.mkdir(parents=True)

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        stale_target = skills_dir / "devflow-replace-skill"

        # On Windows without Developer Mode, creating a real symlink in test setup
        # would fail — which is exactly the bug we're fixing in install.sh.
        # Mock Path.is_symlink so the test doesn't need privilege to create a symlink.
        original_is_symlink = Path.is_symlink

        def mocked_is_symlink(self):
            if str(self) == str(stale_target):
                return True
            return original_is_symlink(self)

        unlinked: list[str] = []
        symlinked: list[str] = []

        with patch.object(Path, "is_symlink", mocked_is_symlink), \
             patch.object(Path, "unlink", lambda self, **kw: unlinked.append(str(self))), \
             patch("os.symlink", side_effect=lambda s, d: symlinked.append(d)):
            m.link_skills(devflow_dir, skills_dir)

        assert len(unlinked) == 1, "stale symlink must be unlinked before replacement"
        assert len(symlinked) == 1, "new symlink must be created after unlinking stale"

    def test_existing_real_directory_is_skipped(self, tmp_path):
        m = _load_module()
        devflow_dir = tmp_path / "devflow"
        skill_src = devflow_dir / "skills" / "devflow-existing-skill"
        skill_src.mkdir(parents=True)

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Create a real (non-symlink) directory at the target
        existing_dir = skills_dir / "devflow-existing-skill"
        existing_dir.mkdir()
        (existing_dir / "custom.md").write_text("user customizations")

        with patch("os.symlink") as mock_symlink, \
             patch("shutil.copytree") as mock_copy:
            m.link_skills(devflow_dir, skills_dir)

        mock_symlink.assert_not_called()
        mock_copy.assert_not_called()
        # Original content preserved
        assert (existing_dir / "custom.md").read_text() == "user customizations"

    def test_only_devflow_prefixed_dirs_are_linked(self, tmp_path):
        m = _load_module()
        devflow_dir = tmp_path / "devflow"
        # Create a non-devflow dir that should be ignored
        (devflow_dir / "skills" / "other-skill").mkdir(parents=True)
        (devflow_dir / "skills" / "devflow-valid-skill").mkdir(parents=True)

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        linked = []

        def track(src, dst):
            linked.append(Path(dst).name)

        with patch("os.symlink", side_effect=track):
            m.link_skills(devflow_dir, skills_dir)

        assert "devflow-valid-skill" in linked
        assert "other-skill" not in linked, "non-devflow dirs must not be linked"
