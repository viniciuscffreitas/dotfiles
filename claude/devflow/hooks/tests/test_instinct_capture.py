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


# ---------------------------------------------------------------------------
# InstinctStore — update_status, pending, report
# ---------------------------------------------------------------------------

def test_store_pending_filters_by_status(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(id="pend001", status="pending"))
    store.append(_make_instinct(id="prom001", status="promoted"))
    store.append(_make_instinct(id="dism001", status="dismissed"))
    pending = store.pending("test-proj")
    assert len(pending) == 1
    assert pending[0].id == "pend001"


def test_store_update_status_changes_status_and_returns_true(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(id="upd00001", status="pending"))
    result = store.update_status("upd00001", "test-proj", "dismissed")
    assert result is True
    loaded = store.load("test-proj")
    assert loaded[0].status == "dismissed"


def test_store_update_status_sets_promoted_to(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(id="prm00001", status="pending"))
    store.update_status("prm00001", "test-proj", "promoted", promoted_to="/rules/foo.md")
    loaded = store.load("test-proj")
    assert loaded[0].promoted_to == "/rules/foo.md"
    assert loaded[0].status == "promoted"


def test_store_update_status_returns_false_for_unknown_id(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(id="known001"))
    result = store.update_status("unknown1", "test-proj", "dismissed")
    assert result is False


def test_store_report_counts_match_actual_data(tmp_path):
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(id="r0000001", status="pending"))
    store.append(_make_instinct(id="r0000002", status="pending"))
    store.append(_make_instinct(id="r0000003", status="promoted"))
    store.append(_make_instinct(id="r0000004", status="dismissed"))
    report = store.report("test-proj")
    assert report.total_captured == 4
    assert report.pending_count == 2
    assert report.promoted_count == 1
    assert report.dismissed_count == 1
    assert report.project == "test-proj"
    assert len(report.instincts) == 4
