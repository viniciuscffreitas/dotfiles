# analysis/instinct_store.py
"""
Instinct storage layer — JSONL persistence per project.
Storage: ~/.claude/devflow/instincts/{project}.jsonl
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_INSTINCTS_DIR = Path.home() / ".claude" / "devflow" / "instincts"


@dataclass
class Instinct:
    id: str                       # uuid4 short (8 chars)
    project: str                  # derived from cwd basename
    captured_at: str              # ISO timestamp
    session_id: str               # CLAUDE_SESSION_ID or pid fallback
    content: str                  # the atomic learning (1-3 sentences)
    confidence: float             # 0.3-0.9
    category: str                 # "pattern"|"preference"|"convention"|"pitfall"
    status: str = "pending"       # "pending"|"promoted"|"dismissed"
    promoted_to: Optional[str] = None  # path of rule file if promoted


@dataclass
class InstinctReport:
    generated_at: str
    project: str
    total_captured: int
    pending_count: int
    promoted_count: int
    dismissed_count: int
    instincts: list[Instinct]


class InstinctStore:
    """
    Persists instincts as JSONL per project.
    Storage: ~/.claude/devflow/instincts/{project}.jsonl
    One Instinct per line, append-only.
    """

    def __init__(self, base_dir: Path = _INSTINCTS_DIR) -> None:
        self._base = base_dir

    def _path(self, project: str) -> Path:
        return self._base / f"{project}.jsonl"

    def append(self, instinct: Instinct) -> None:
        """Append instinct to project file. Creates file if missing."""
        p = self._path(instinct.project)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dataclasses.asdict(instinct)) + "\n")

    def load(self, project: str) -> list[Instinct]:
        """Load all instincts for a project."""
        p = self._path(project)
        if not p.exists():
            return []
        result: list[Instinct] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                result.append(Instinct(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return result
