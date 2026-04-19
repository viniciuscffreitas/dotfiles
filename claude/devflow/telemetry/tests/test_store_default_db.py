"""
Tests for DEVFLOW_TELEMETRY_DB env-var override of the default DB path.

Contract:
  CHANGES  - TelemetryStore() with no args honors DEVFLOW_TELEMETRY_DB
  CHANGES  - override is read at instantiation (not import) time
  MUST NOT - production path leaks into tests that rely on the env var
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "telemetry"))
from store import TelemetryStore, _DEFAULT_DB, _resolve_default_db


def test_resolve_default_db_returns_production_when_unset(monkeypatch):
    monkeypatch.delenv("DEVFLOW_TELEMETRY_DB", raising=False)
    assert _resolve_default_db() == _DEFAULT_DB


def test_resolve_default_db_honors_env_var(monkeypatch, tmp_path):
    target = tmp_path / "alt.db"
    monkeypatch.setenv("DEVFLOW_TELEMETRY_DB", str(target))
    assert _resolve_default_db() == target


def test_store_without_args_writes_to_env_var_path(monkeypatch, tmp_path):
    target = tmp_path / "redirected.db"
    monkeypatch.setenv("DEVFLOW_TELEMETRY_DB", str(target))
    store = TelemetryStore()
    store.record({"task_id": "redirect-check", "judge_verdict": "pass"})
    assert target.exists()


def test_store_explicit_path_overrides_env_var(monkeypatch, tmp_path):
    env_target = tmp_path / "env.db"
    explicit_target = tmp_path / "explicit.db"
    monkeypatch.setenv("DEVFLOW_TELEMETRY_DB", str(env_target))
    store = TelemetryStore(db_path=explicit_target)
    store.record({"task_id": "explicit", "judge_verdict": "pass"})
    assert explicit_target.exists()
    assert not env_target.exists()
