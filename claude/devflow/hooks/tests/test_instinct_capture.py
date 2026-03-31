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


# ---------------------------------------------------------------------------
# instinct_capture — _parse_transcript
# ---------------------------------------------------------------------------

# Import after sys.path is set up (path already inserted at top of file)
from instinct_capture import _parse_transcript


def test_parse_transcript_counts_tool_uses(tmp_path):
    jsonl = tmp_path / "sess.jsonl"
    entry = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Read", "id": "t1", "input": {}},
                {"type": "tool_use", "name": "Write", "id": "t2", "input": {}},
                {"type": "text", "text": "I'll implement this now."},
            ],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
    })
    jsonl.write_text(entry + "\n")
    count, texts = _parse_transcript(jsonl, n_messages=5)
    assert count == 2
    assert texts == ["I'll implement this now."]


def test_parse_transcript_returns_last_n_assistant_texts(tmp_path):
    jsonl = tmp_path / "sess.jsonl"
    entries = []
    for i in range(7):
        entries.append(json.dumps({
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": f"Message {i}"}],
                "usage": {},
            },
        }))
    jsonl.write_text("\n".join(entries) + "\n")
    _, texts = _parse_transcript(jsonl, n_messages=3)
    assert len(texts) == 3
    assert texts[-1] == "Message 6"


def test_parse_transcript_ignores_non_assistant_entries(tmp_path):
    jsonl = tmp_path / "sess.jsonl"
    entries = [
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "Do X"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}], "usage": {}}}),
    ]
    jsonl.write_text("\n".join(entries) + "\n")
    count, texts = _parse_transcript(jsonl, n_messages=5)
    assert count == 1
    assert texts == []


# ---------------------------------------------------------------------------
# instinct_capture — skip conditions (subprocess)
# ---------------------------------------------------------------------------

import subprocess as _sp

_CAPTURE_SCRIPT = str(Path(__file__).parent.parent / "instinct_capture.py")


def test_capture_skips_when_instinct_skip_env_set():
    result = _sp.run(
        ["python3.13", _CAPTURE_SCRIPT],
        env={**os.environ, "DEVFLOW_INSTINCT_SKIP": "1"},
        input="{}",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_capture_skips_when_project_is_devflow():
    hook_data = json.dumps({"session_id": "sess-001", "cwd": "/Users/vini/.claude/devflow"})
    result = _sp.run(
        ["python3.13", _CAPTURE_SCRIPT],
        input=hook_data,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "[devflow:instinct] captured" not in result.stdout


def test_capture_always_exits_0_with_skip():
    result = _sp.run(
        ["python3.13", _CAPTURE_SCRIPT],
        env={**os.environ, "DEVFLOW_INSTINCT_SKIP": "1"},
        input="{}",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# instinct_capture — _call_haiku + full hook behavior
# ---------------------------------------------------------------------------

from instinct_capture import _call_haiku, main as capture_main
import instinct_capture as _ic


def test_call_haiku_uses_haiku_model():
    """Verifies claude -p is called with the Haiku model."""
    captured_args: list[str] = []

    def fake_run(args, **kwargs):
        captured_args.extend(args)
        m = MagicMock()
        m.returncode = 0
        m.stdout = '[{"content": "Use Riverpod.", "confidence": 0.8, "category": "pattern"}]'
        m.stderr = ""
        return m

    with patch("instinct_capture.subprocess.run", side_effect=fake_run):
        result = _call_haiku("transcript text")

    assert "claude" in captured_args
    assert "-p" in captured_args
    assert "claude-haiku-4-5-20251001" in captured_args
    assert len(result) == 1
    assert result[0]["content"] == "Use Riverpod."


def test_call_haiku_parses_valid_json_array():
    def fake_run(args, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = '[{"content": "A", "confidence": 0.7, "category": "pitfall"}, {"content": "B", "confidence": 0.5, "category": "convention"}]'
        m.stderr = ""
        return m

    with patch("instinct_capture.subprocess.run", side_effect=fake_run):
        result = _call_haiku("some text")

    assert len(result) == 2
    assert result[0]["category"] == "pitfall"


def test_call_haiku_strips_markdown_fences():
    def fake_run(args, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = '```json\n[{"content": "X", "confidence": 0.6, "category": "pattern"}]\n```'
        m.stderr = ""
        return m

    with patch("instinct_capture.subprocess.run", side_effect=fake_run):
        result = _call_haiku("text")

    assert len(result) == 1
    assert result[0]["content"] == "X"


def test_call_haiku_raises_on_subprocess_failure():
    import subprocess as _subprocess
    def fake_run(args, **kwargs):
        m = MagicMock()
        m.returncode = 1
        m.stdout = ""
        m.stderr = "error"
        return m

    with patch("instinct_capture.subprocess.run", side_effect=fake_run):
        with pytest.raises(_subprocess.SubprocessError):
            _call_haiku("text")


def test_call_haiku_raises_on_unparseable_response():
    def fake_run(args, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = "not valid json"
        m.stderr = ""
        return m

    with patch("instinct_capture.subprocess.run", side_effect=fake_run):
        with pytest.raises(json.JSONDecodeError):
            _call_haiku("text")


def _make_session_jsonl(tmp_path: Path, n_tool_uses: int, texts: list[str]) -> Path:
    """Create a session JSONL with n tool_uses and given text messages."""
    p = tmp_path / "sess.jsonl"
    entries = []
    for _ in range(n_tool_uses):
        entries.append(json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Read", "id": "t1", "input": {}}], "usage": {}},
        }))
    for text in texts:
        entries.append(json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}], "usage": {}},
        }))
    p.write_text("\n".join(entries) + "\n")
    return p


def test_capture_handles_unparseable_llm_response_gracefully(tmp_path):
    """When LLM returns garbage JSON, capture exits 0."""
    session_jsonl = _make_session_jsonl(tmp_path, n_tool_uses=5, texts=["Some text."])
    instincts_dir = tmp_path / "instincts"

    def fake_run(args, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = "not json at all"
        m.stderr = ""
        return m

    with (
        patch.object(_ic, "_find_session_jsonl", return_value=session_jsonl),
        patch.object(_ic, "subprocess") as mock_subp,
        patch.object(_ic, "read_hook_stdin", return_value={"session_id": "s1", "cwd": "/proj/alpha"}),
        patch.object(_ic, "InstinctStore", return_value=InstinctStore(base_dir=instincts_dir)),
    ):
        mock_subp.run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        mock_subp.SubprocessError = __import__("subprocess").SubprocessError
        mock_subp.TimeoutExpired = __import__("subprocess").TimeoutExpired
        code = _ic.main()
    assert code == 0


def test_capture_handles_subprocess_failure_gracefully(tmp_path):
    """When claude subprocess fails, capture exits 0."""
    session_jsonl = _make_session_jsonl(tmp_path, n_tool_uses=5, texts=["Some text."])
    instincts_dir = tmp_path / "instincts"

    def fake_run(args, **kwargs):
        m = MagicMock()
        m.returncode = 1
        m.stdout = ""
        m.stderr = "failure"
        return m

    with (
        patch.object(_ic, "_find_session_jsonl", return_value=session_jsonl),
        patch.object(_ic, "subprocess") as mock_subp,
        patch.object(_ic, "read_hook_stdin", return_value={"session_id": "s1", "cwd": "/proj/beta"}),
        patch.object(_ic, "InstinctStore", return_value=InstinctStore(base_dir=instincts_dir)),
    ):
        mock_subp.run.return_value = MagicMock(returncode=1, stdout="", stderr="failure")
        mock_subp.SubprocessError = __import__("subprocess").SubprocessError
        mock_subp.TimeoutExpired = __import__("subprocess").TimeoutExpired
        code = _ic.main()
    assert code == 0


def test_capture_prints_devflow_instinct_prefix_on_success(tmp_path, capsys):
    """When LLM returns valid JSON, prints [devflow:instinct] captured N."""
    session_jsonl = _make_session_jsonl(tmp_path, n_tool_uses=5, texts=["Did something useful."])
    instincts_dir = tmp_path / "instincts"

    def fake_run(args, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = '[{"content": "Use X for Y.", "confidence": 0.8, "category": "pattern"}]'
        m.stderr = ""
        return m

    with (
        patch.object(_ic, "_find_session_jsonl", return_value=session_jsonl),
        patch.object(_ic, "subprocess") as mock_subp,
        patch.object(_ic, "read_hook_stdin", return_value={"session_id": "sess-t1", "cwd": "/proj/mom-ease"}),
        patch.object(_ic, "InstinctStore", return_value=InstinctStore(base_dir=instincts_dir)),
    ):
        mock_subp.run.side_effect = fake_run
        mock_subp.SubprocessError = __import__("subprocess").SubprocessError
        mock_subp.TimeoutExpired = __import__("subprocess").TimeoutExpired
        code = _ic.main()

    assert code == 0
    captured = capsys.readouterr()
    assert "[devflow:instinct]" in captured.out
    assert "captured" in captured.out
    assert "mom-ease" in captured.out


def test_capture_skips_when_tool_use_count_less_than_3(tmp_path):
    """Session with < 3 tool uses is skipped."""
    session_jsonl = _make_session_jsonl(tmp_path, n_tool_uses=2, texts=["Some text."])

    with (
        patch.object(_ic, "_find_session_jsonl", return_value=session_jsonl),
        patch.object(_ic, "read_hook_stdin", return_value={"session_id": "sess-short", "cwd": "/proj/alpha"}),
    ):
        code = _ic.main()
    assert code == 0


# ---------------------------------------------------------------------------
# instinct_review CLI
# ---------------------------------------------------------------------------

import subprocess as _sprev

_REVIEW_CLI = str(Path(__file__).parent.parent / "instinct_review.py")


def _run_review(*args: str, input_text: str = "") -> tuple[str, int]:
    result = _sprev.run(
        ["python3.13", _REVIEW_CLI, *args],
        capture_output=True,
        text=True,
        input=input_text,
    )
    return result.stdout + result.stderr, result.returncode


def test_review_default_output_contains_devflow_instincts_label():
    out, code = _run_review("--project", "nonexistent-project-xyzzy")
    assert code == 0
    assert "[devflow:instincts]" in out


def test_review_json_output_is_valid_json_with_required_keys():
    out, code = _run_review("--project", "nonexistent-project-xyzzy", "--json")
    assert code == 0
    data = json.loads(out)
    assert "pending_count" in data
    assert "project" in data


def test_review_json_all_aggregates_across_projects(tmp_path):
    from instinct_review import main as review_main
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(project="proj-a", id="aa000001"))
    store.append(_make_instinct(project="proj-b", id="bb000001"))

    from io import StringIO
    import sys as _sys
    old_stdout = _sys.stdout
    _sys.stdout = buf = StringIO()
    try:
        with patch("instinct_review._INSTINCTS_DIR", tmp_path):
            with patch("instinct_review.InstinctStore", return_value=store):
                review_main(["--all", "--json"])
    finally:
        _sys.stdout = old_stdout

    data = json.loads(buf.getvalue())
    assert isinstance(data, list)
    projects = {d["project"] for d in data}
    assert "proj-a" in projects
    assert "proj-b" in projects


def test_review_promote_updates_status_to_promoted(tmp_path):
    from instinct_review import _promote
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(project="my-proj", id="prm12345", status="pending"))
    instinct = store.load("my-proj")[0]
    rules_file = tmp_path / "rules.md"

    with patch("builtins.input", return_value=str(rules_file)):
        _promote(store, instinct, "my-proj")

    updated = store.load("my-proj")[0]
    assert updated.status == "promoted"
    assert updated.promoted_to == str(rules_file)
    assert rules_file.exists()
    assert "Use Riverpod for state." in rules_file.read_text()


def test_review_dismiss_updates_status_to_dismissed(tmp_path):
    from instinct_review import main as review_main
    store = InstinctStore(base_dir=tmp_path)
    store.append(_make_instinct(project="dismiss-proj", id="dis12345", status="pending"))

    with (
        patch("instinct_review.InstinctStore", return_value=store),
        patch("builtins.input", return_value="d"),
    ):
        review_main(["--project", "dismiss-proj"])

    updated = store.load("dismiss-proj")[0]
    assert updated.status == "dismissed"


# ---------------------------------------------------------------------------
# WeeklySignals — instinct fields + recommendation
# ---------------------------------------------------------------------------

from analysis.weekly_report import WeeklySignals, WeeklyReportGenerator
from analysis.harness_health import HarnessHealthReport


def _make_signals_with_instincts(**kwargs) -> WeeklySignals:
    defaults = dict(
        week_start="2026-03-30",
        week_end="2026-04-05",
        sessions_total=10,
        sessions_with_data=8,
        judge_pass_rate=0.85,
        judge_fail_rate=0.15,
        mean_anxiety_score=0.3,
        high_anxiety_sessions=1,
        top_fail_categories=[],
        top_lob_violations=0,
        top_duplication_count=0,
        harness_health="healthy",
        stale_skill_count=0,
        broken_hook_count=0,
        instincts_captured=0,
        instincts_pending=0,
    )
    defaults.update(kwargs)
    return WeeklySignals(**defaults)


def test_weekly_signals_has_instincts_captured_field():
    s = _make_signals_with_instincts(instincts_captured=3)
    assert s.instincts_captured == 3


def test_weekly_signals_has_instincts_pending_field():
    s = _make_signals_with_instincts(instincts_pending=7)
    assert s.instincts_pending == 7


def test_generate_recommendations_instincts_pending_over_5_triggers_medium():
    gen = WeeklyReportGenerator()
    signals = _make_signals_with_instincts(instincts_pending=6)
    health = HarnessHealthReport(
        generated_at="2026-03-31T00:00:00+00:00",
        overall_verdict="healthy",
        skill_health=[],
        hook_health=[],
        stale_skill_count=0,
        broken_hook_count=0,
        simplification_candidates=[],
        complexity_score=0.0,
        summary="All good.",
    )
    recs = gen._generate_recommendations(signals, health)
    instinct_recs = [r for r in recs if "instinct" in r.action.lower()]
    assert len(instinct_recs) >= 1
    assert instinct_recs[0].priority == "medium"
