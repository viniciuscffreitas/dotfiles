"""
Cross-platform skill linking for devflow install.

Replaces the bash 'ln -s' in install.sh which fails on Windows without
Developer Mode or admin privileges. Tries os.symlink first; falls back to
shutil.copytree when symlink creation is not permitted (OSError).

Can be called directly:
    python3 install_skills.py <devflow_dir> <skills_dir>

Or imported in tests:
    from install_skills import link_skills
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def link_skills(devflow_dir: Path, skills_dir: Path) -> None:
    """Link all devflow-* skill directories from devflow_dir/skills/ into skills_dir.

    For each skill:
    - If a symlink already exists at the target: replace it.
    - If a real directory already exists: skip (preserves user customisations).
    - Try os.symlink first (preferred — stays in sync with repo).
    - On OSError (Windows without Developer Mode, insufficient privileges):
      fall back to shutil.copytree.

    Args:
        devflow_dir: Root of the devflow repository.
        skills_dir:  Destination directory where skill dirs should appear.
    """
    devflow_dir = Path(devflow_dir)
    skills_dir = Path(skills_dir)
    skills_dir.mkdir(parents=True, exist_ok=True)

    skill_sources = sorted(devflow_dir.glob("skills/devflow-*/"))

    for skill_dir in skill_sources:
        skill_name = skill_dir.name
        target = skills_dir / skill_name

        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            print(f"  SKIP: {skill_name} (already exists as directory, not overwriting)")
            continue

        try:
            os.symlink(str(skill_dir.resolve()), str(target))
            print(f"  OK (symlink): {skill_name}")
        except OSError:
            # Windows without Developer Mode or SeCreateSymbolicLinkPrivilege:
            # fall back to a directory copy. Note: copy is NOT auto-updated when
            # the repo changes — re-run install.sh to refresh.
            shutil.copytree(str(skill_dir), str(target))
            print(f"  OK (copy): {skill_name}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <devflow_dir> <skills_dir>", file=sys.stderr)
        sys.exit(1)
    link_skills(Path(sys.argv[1]), Path(sys.argv[2]))
