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


# ---------------------------------------------------------------------------
# InstinctStore — append + load
# ---------------------------------------------------------------------------

def _make_instinct(project="test-proj", id="ab1234cd", status="pending") -> Instinct:
    return Instinct(
        id=id,
        project=project,
        captured_at="2026-03-31T00:00:00+00:00",
        session_id="sess-001",
        content="Use Riverpod for state.",
        confidence=0.8,
        category="pattern",
        status=status,
        promoted_to=None,
    )


def test_store_append_creates_file_if_missing(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    i = _make_instinct()
    store.append(i)
    p = tmp_path / "test-proj.jsonl"
    assert p.exists()
    lines = [l for l in p.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "ab1234cd"


def test_store_load_returns_all_instincts_for_project(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(id="id000001"))
    store.append(_make_instinct(id="id000002"))
    store.append(_make_instinct(id="id000003"))
    result = store.load("test-proj")
    assert len(result) == 3
    assert all(isinstance(i, Instinct) for i in result)


def test_store_never_raises_on_missing_file(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    result = store.load("no-such-project")
    assert result == []


def test_store_multiple_projects_are_isolated(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(project="proj-a", id="aa000001"))
    store.append(_make_instinct(project="proj-b", id="bb000001"))
    store.append(_make_instinct(project="proj-b", id="bb000002"))
    assert len(store.load("proj-a")) == 1
    assert len(store.load("proj-b")) == 2
