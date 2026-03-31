"""Tests for instinct capture — dataclasses, store, hook, review CLI."""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from analysis.instinct_store import Instinct, InstinctReport, InstinctStore


# ---------------------------------------------------------------------------
# Instinct dataclass
# ---------------------------------------------------------------------------

def test_instinct_instantiates_with_all_fields():
    i = Instinct(
        id="abc12345",
        project="mom-ease",
        captured_at="2026-03-31T00:00:00+00:00",
        session_id="sess-001",
        content="Use Riverpod for state management.",
        confidence=0.8,
        category="pattern",
        status="pending",
        promoted_to=None,
    )
    assert i.id == "abc12345"
    assert i.project == "mom-ease"
    assert i.status == "pending"
    assert i.promoted_to is None


def test_instinct_status_defaults_to_pending():
    i = Instinct(
        id="abc12345",
        project="mom-ease",
        captured_at="2026-03-31T00:00:00+00:00",
        session_id="sess-001",
        content="Some learning.",
        confidence=0.7,
        category="convention",
    )
    assert i.status == "pending"
    assert i.promoted_to is None


def test_instinct_id_is_8_char_string():
    i = Instinct(
        id="ab1234cd",
        project="sekit",
        captured_at="2026-03-31T00:00:00+00:00",
        session_id="sess-002",
        content="Content.",
        confidence=0.5,
        category="pitfall",
    )
    assert isinstance(i.id, str)
    assert len(i.id) == 8
