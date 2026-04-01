# LLM-as-Judge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a semantic quality evaluator that grades agent-produced diffs against a rubric, routing results through oversight levels to produce pass/warn/fail/skipped verdicts stored in TelemetryStore.

**Architecture:** A pure `HarnessJudge` class calls Claude Haiku via subprocess (`claude -p`) with an isolated, rubric-structured prompt and parses the JSON response into a typed `JudgeResult`. A `JudgeRouter` maps oversight levels to blocking behaviour. A Stop hook (`post_task_judge.py`) wires them together, reads state files, and writes telemetry.

**Tech Stack:** Python 3.13, dataclasses, subprocess, anthropic SDK (optional fallback), pytest, existing `TelemetryStore` and `_util.py` helpers.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `judge/__init__.py` | Create | Package marker (empty) |
| `judge/evaluator.py` | Create | `JudgePayload`, `JudgeResult`, `HarnessJudge` |
| `judge/router.py` | Create | `JudgeRouter` — routing + blocking + state writes |
| `judge/calibration/pass_001.json` | Create | Ground truth: clean well-scoped feature |
| `judge/calibration/pass_002.json` | Create | Ground truth: adds tests, no duplication |
| `judge/calibration/warn_001.json` | Create | Ground truth: missing edge cases |
| `judge/calibration/fail_001.json` | Create | Ground truth: LoB violation |
| `judge/calibration/fail_002.json` | Create | Ground truth: unjustified complexity |
| `hooks/post_task_judge.py` | Create | Stop hook orchestrator |
| `hooks/tests/test_judge.py` | Create | ~35 tests covering all components |

---

## Task 1: Data classes — JudgePayload and JudgeResult

**Files:**
- Create: `judge/__init__.py`
- Create: `judge/evaluator.py` (data classes only — no HarnessJudge yet)
- Create: `hooks/tests/test_judge.py` (data class tests)

- [ ] **Step 1: Write the failing tests for data classes**

```python
# hooks/tests/test_judge.py
"""Tests for HarnessJudge, JudgeRouter, and post_task_judge hook."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from judge.evaluator import JudgePayload, JudgeResult, HarnessJudge
from judge.router import JudgeRouter


# ---------------------------------------------------------------------------
# JudgePayload and JudgeResult
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_judge_payload_fields(self):
        p = JudgePayload(
            diff="diff --git a/foo.py",
            spec="add feature X",
            harness_rules=["no mocks", "TDD"],
            existing_code="def foo(): pass",
            feature_path="lib/features/user/",
            task_id="abc-123",
        )
        assert p.diff == "diff --git a/foo.py"
        assert p.task_id == "abc-123"
        assert p.harness_rules == ["no mocks", "TDD"]

    def test_judge_result_default_fields(self):
        r = JudgeResult(
            task_id="t1",
            verdict="pass",
            lob_violation=False,
            lob_evidence=None,
            duplication=False,
            duplication_evidence=None,
            type_contract_violation=False,
            type_contract_evidence=None,
            unjustified_complexity=False,
            complexity_evidence=None,
            naming_consistency_score=1.0,
            naming_evidence=None,
            edge_case_coverage="adequate",
            spec_fulfilled="yes",
            spec_evidence=None,
            fail_reasons=[],
            raw_response=None,
        )
        assert r.verdict == "pass"
        assert r.lob_violation is False
        assert r.fail_reasons == []
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestDataClasses -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'judge'`

- [ ] **Step 3: Create `judge/__init__.py` (empty)**

```python
# judge/__init__.py
```

- [ ] **Step 4: Create `judge/evaluator.py` with data classes**

```python
# judge/evaluator.py
"""
HarnessJudge — LLM-as-judge for semantic quality evaluation.

Grades the final state of a diff against a rubric.
Never raises — always returns a JudgeResult.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class JudgePayload:
    diff: str              # git diff of changes made
    spec: str              # task description / plan_path content
    harness_rules: list    # list of rule strings from CLAUDE.md
    existing_code: str     # preexisting code in modified area
    feature_path: str      # expected LoB boundary (e.g. "lib/features/user/")
    task_id: str           # for telemetry correlation


@dataclass
class JudgeResult:
    task_id: str
    verdict: str                        # pass | warn | fail | skipped
    lob_violation: bool
    lob_evidence: str | None
    duplication: bool
    duplication_evidence: str | None
    type_contract_violation: bool
    type_contract_evidence: str | None
    unjustified_complexity: bool
    complexity_evidence: str | None
    naming_consistency_score: float     # 0.0–1.0
    naming_evidence: str | None
    edge_case_coverage: str             # none | minimal | adequate | thorough
    spec_fulfilled: str                 # yes | partial | no
    spec_evidence: str | None
    fail_reasons: list = field(default_factory=list)
    raw_response: str | None = None


class HarnessJudge:
    pass  # implementation follows in Task 2
```

- [ ] **Step 5: Run to verify tests pass**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestDataClasses -v
```
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
cd /Users/vini/.claude/devflow && git add judge/__init__.py judge/evaluator.py hooks/tests/test_judge.py
git commit -m "feat(judge): add JudgePayload and JudgeResult data classes with tests"
```

---

## Task 2: HarnessJudge._build_prompt

**Files:**
- Modify: `judge/evaluator.py` — add `_build_prompt` to `HarnessJudge`
- Modify: `hooks/tests/test_judge.py` — add `TestBuildPrompt` class

- [ ] **Step 1: Write failing tests for _build_prompt**

Add to `hooks/tests/test_judge.py`:

```python
# ---------------------------------------------------------------------------
# HarnessJudge._build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def setup_method(self):
        self.judge = HarnessJudge()

    def test_prompt_includes_diff(self):
        payload = JudgePayload(
            diff="diff --git a/foo.py\n+def bar(): pass",
            spec="add bar function",
            harness_rules=["no mocks"],
            existing_code="def foo(): pass",
            feature_path="lib/",
            task_id="t1",
        )
        prompt = self.judge._build_prompt(payload)
        assert "diff --git a/foo.py" in prompt

    def test_prompt_includes_spec(self):
        payload = JudgePayload(
            diff="some diff",
            spec="implement feature ZETA",
            harness_rules=[],
            existing_code="",
            feature_path=".",
            task_id="t2",
        )
        prompt = self.judge._build_prompt(payload)
        assert "implement feature ZETA" in prompt

    def test_prompt_includes_harness_rules(self):
        payload = JudgePayload(
            diff="d",
            spec="s",
            harness_rules=["rule one", "rule two"],
            existing_code="",
            feature_path=".",
            task_id="t3",
        )
        prompt = self.judge._build_prompt(payload)
        assert "rule one" in prompt
        assert "rule two" in prompt

    def test_prompt_system_instruction_no_prose(self):
        payload = JudgePayload(
            diff="d", spec="s", harness_rules=[], existing_code="", feature_path=".", task_id="t4",
        )
        prompt = self.judge._build_prompt(payload)
        assert "Respond ONLY with valid JSON" in prompt

    def test_prompt_includes_feature_path(self):
        payload = JudgePayload(
            diff="d", spec="s", harness_rules=[], existing_code="",
            feature_path="lib/features/user/", task_id="t5",
        )
        prompt = self.judge._build_prompt(payload)
        assert "lib/features/user/" in prompt
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestBuildPrompt -v 2>&1 | head -20
```
Expected: `AttributeError: 'HarnessJudge' object has no attribute '_build_prompt'`

- [ ] **Step 3: Implement `HarnessJudge.__init__` and `_build_prompt`**

Replace the `class HarnessJudge: pass` stub in `judge/evaluator.py` with:

```python
class HarnessJudge:

    _SYSTEM = (
        "You are a code quality evaluator. Evaluate ONLY the final state of the diff. "
        "Do not consider intermediate steps. "
        "Respond ONLY with valid JSON matching the schema. "
        "No prose. No markdown. No explanation outside the JSON."
    )

    _RUBRIC_SCHEMA = """{
  "lob_violation": {"result": "yes|no", "evidence": "specific import or null"},
  "duplication": {"result": "yes|no", "evidence": "duplicated snippet + existing path or null"},
  "type_contract_violation": {"result": "yes|no|na", "evidence": "line and description or null"},
  "unjustified_complexity": {"result": "yes|no", "evidence": "abstraction description or null"},
  "naming_consistency": {"score": 0.0, "evidence": "inconsistencies or null"},
  "edge_case_coverage": {"level": "none|minimal|adequate|thorough", "missing": []},
  "spec_fulfilled": {"result": "yes|partial|no", "evidence": "what is missing or null"},
  "overall_verdict": "pass|warn|fail",
  "fail_reasons": []
}"""

    _VERDICT_RULES = """Verdict rules:
- fail: lob_violation=yes OR type_contract_violation=yes OR unjustified_complexity=yes OR spec_fulfilled=no
- warn: duplication=yes OR naming_consistency.score < 0.7 OR edge_case_coverage in [none, minimal] OR spec_fulfilled=partial
- pass: none of the above"""

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model

    def _build_prompt(self, payload: JudgePayload) -> str:
        rules_block = "\n".join(f"- {r}" for r in payload.harness_rules) or "(none)"
        return (
            f"{self._SYSTEM}\n\n"
            f"## Task Spec\n{payload.spec}\n\n"
            f"## Expected LoB Boundary\n{payload.feature_path}\n\n"
            f"## Harness Rules\n{rules_block}\n\n"
            f"## Existing Code (context)\n{payload.existing_code}\n\n"
            f"## Diff to Evaluate\n{payload.diff}\n\n"
            f"## Output Schema\n{self._RUBRIC_SCHEMA}\n\n"
            f"{self._VERDICT_RULES}\n\n"
            f"Respond ONLY with valid JSON."
        )

    def _parse_result(self, raw: str, task_id: str = "") -> "JudgeResult":
        pass  # Task 3

    def evaluate(self, payload: JudgePayload) -> "JudgeResult":
        pass  # Task 4
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestBuildPrompt -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow && git add judge/evaluator.py hooks/tests/test_judge.py
git commit -m "feat(judge): implement HarnessJudge._build_prompt with rubric and system instructions"
```

---

## Task 3: HarnessJudge._parse_result

**Files:**
- Modify: `judge/evaluator.py` — implement `_parse_result`
- Modify: `hooks/tests/test_judge.py` — add `TestParseResult` class

- [ ] **Step 1: Write failing tests for _parse_result**

Add to `hooks/tests/test_judge.py`:

```python
# ---------------------------------------------------------------------------
# HarnessJudge._parse_result
# ---------------------------------------------------------------------------

VALID_JUDGE_JSON = {
    "lob_violation": {"result": "no", "evidence": None},
    "duplication": {"result": "no", "evidence": None},
    "type_contract_violation": {"result": "na", "evidence": None},
    "unjustified_complexity": {"result": "no", "evidence": None},
    "naming_consistency": {"score": 0.9, "evidence": None},
    "edge_case_coverage": {"level": "adequate", "missing": []},
    "spec_fulfilled": {"result": "yes", "evidence": None},
    "overall_verdict": "pass",
    "fail_reasons": [],
}

FAIL_JUDGE_JSON = {
    "lob_violation": {"result": "yes", "evidence": "imports from auth feature"},
    "duplication": {"result": "no", "evidence": None},
    "type_contract_violation": {"result": "no", "evidence": None},
    "unjustified_complexity": {"result": "no", "evidence": None},
    "naming_consistency": {"score": 0.8, "evidence": None},
    "edge_case_coverage": {"level": "thorough", "missing": []},
    "spec_fulfilled": {"result": "yes", "evidence": None},
    "overall_verdict": "fail",
    "fail_reasons": ["lob_violation"],
}


class TestParseResult:
    def setup_method(self):
        self.judge = HarnessJudge()

    def test_parses_valid_json(self):
        raw = json.dumps(VALID_JUDGE_JSON)
        result = self.judge._parse_result(raw, task_id="t1")
        assert result.verdict == "pass"
        assert result.lob_violation is False
        assert result.naming_consistency_score == pytest.approx(0.9)
        assert result.edge_case_coverage == "adequate"
        assert result.spec_fulfilled == "yes"

    def test_strips_json_fences(self):
        raw = "```json\n" + json.dumps(VALID_JUDGE_JSON) + "\n```"
        result = self.judge._parse_result(raw, task_id="t2")
        assert result.verdict == "pass"

    def test_strips_json_fence_no_language(self):
        raw = "```\n" + json.dumps(VALID_JUDGE_JSON) + "\n```"
        result = self.judge._parse_result(raw, task_id="t3")
        assert result.verdict == "pass"

    def test_invalid_json_returns_skipped(self):
        result = self.judge._parse_result("not json at all", task_id="t4")
        assert result.verdict == "skipped"
        assert result.task_id == "t4"

    def test_empty_string_returns_skipped(self):
        result = self.judge._parse_result("", task_id="t5")
        assert result.verdict == "skipped"

    def test_parses_fail_verdict(self):
        raw = json.dumps(FAIL_JUDGE_JSON)
        result = self.judge._parse_result(raw, task_id="t6")
        assert result.verdict == "fail"
        assert result.lob_violation is True
        assert result.lob_evidence == "imports from auth feature"
        assert "lob_violation" in result.fail_reasons

    def test_raw_response_preserved(self):
        raw = json.dumps(VALID_JUDGE_JSON)
        result = self.judge._parse_result(raw, task_id="t7")
        assert result.raw_response == raw
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestParseResult -v 2>&1 | head -20
```
Expected: errors because `_parse_result` returns `None`

- [ ] **Step 3: Implement `_parse_result`**

Replace `pass` in `_parse_result` with:

```python
    def _parse_result(self, raw: str, task_id: str = "") -> "JudgeResult":
        try:
            # Strip ```json ... ``` or ``` ... ``` fences
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip())
            data = json.loads(cleaned)

            lob = data.get("lob_violation", {})
            dup = data.get("duplication", {})
            tc = data.get("type_contract_violation", {})
            uc = data.get("unjustified_complexity", {})
            nc = data.get("naming_consistency", {})
            ec = data.get("edge_case_coverage", {})
            sf = data.get("spec_fulfilled", {})

            return JudgeResult(
                task_id=task_id,
                verdict=str(data.get("overall_verdict", "skipped")),
                lob_violation=lob.get("result") == "yes",
                lob_evidence=lob.get("evidence"),
                duplication=dup.get("result") == "yes",
                duplication_evidence=dup.get("evidence"),
                type_contract_violation=tc.get("result") == "yes",
                type_contract_evidence=tc.get("evidence"),
                unjustified_complexity=uc.get("result") == "yes",
                complexity_evidence=uc.get("evidence"),
                naming_consistency_score=float(nc.get("score", 1.0)),
                naming_evidence=nc.get("evidence"),
                edge_case_coverage=str(ec.get("level", "adequate")),
                spec_fulfilled=str(sf.get("result", "yes")),
                spec_evidence=sf.get("evidence"),
                fail_reasons=list(data.get("fail_reasons", [])),
                raw_response=raw,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return JudgeResult(
                task_id=task_id,
                verdict="skipped",
                lob_violation=False,
                lob_evidence=None,
                duplication=False,
                duplication_evidence=None,
                type_contract_violation=False,
                type_contract_evidence=None,
                unjustified_complexity=False,
                complexity_evidence=None,
                naming_consistency_score=1.0,
                naming_evidence=None,
                edge_case_coverage="adequate",
                spec_fulfilled="yes",
                spec_evidence=None,
                fail_reasons=[],
                raw_response=raw or None,
            )
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestParseResult -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow && git add judge/evaluator.py hooks/tests/test_judge.py
git commit -m "feat(judge): implement _parse_result with JSON fence stripping and skipped fallback"
```

---

## Task 4: HarnessJudge.evaluate() with timeout + verdict mapping

**Files:**
- Modify: `judge/evaluator.py` — implement `evaluate()`
- Modify: `hooks/tests/test_judge.py` — add `TestEvaluate` and `TestVerdictMapping`

- [ ] **Step 1: Write failing tests for evaluate() and verdict mapping**

Add to `hooks/tests/test_judge.py`:

```python
# ---------------------------------------------------------------------------
# HarnessJudge.evaluate()
# ---------------------------------------------------------------------------

class TestEvaluate:
    def setup_method(self):
        self.judge = HarnessJudge()
        self.payload = JudgePayload(
            diff="diff --git a/foo.py\n+def bar(): pass",
            spec="add bar function",
            harness_rules=["TDD required"],
            existing_code="def foo(): pass",
            feature_path="lib/features/",
            task_id="eval-001",
        )

    def _make_mock_result(self):
        return json.dumps(VALID_JUDGE_JSON)

    def test_returns_judge_result_on_valid_response(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=self._make_mock_result(), stderr="")
            result = self.judge.evaluate(self.payload)
        assert isinstance(result, JudgeResult)
        assert result.verdict == "pass"
        assert result.task_id == "eval-001"

    def test_returns_skipped_on_timeout(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=30)
            result = self.judge.evaluate(self.payload)
        assert result.verdict == "skipped"
        assert result.task_id == "eval-001"

    def test_never_raises_on_any_input(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("unexpected failure")
            result = self.judge.evaluate(self.payload)
        assert isinstance(result, JudgeResult)
        assert result.verdict == "skipped"

    def test_never_raises_on_empty_payload(self):
        empty_payload = JudgePayload(
            diff="", spec="", harness_rules=[], existing_code="", feature_path="", task_id="empty",
        )
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("fail")
            result = self.judge.evaluate(empty_payload)
        assert isinstance(result, JudgeResult)

    def test_subprocess_called_with_model(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=self._make_mock_result(), stderr="")
            self.judge.evaluate(self.payload)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "claude" in cmd[0]
        assert "--model" in cmd or any("haiku" in str(a) for a in cmd)

    def test_nonzero_exit_returns_skipped(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="API error")
            result = self.judge.evaluate(self.payload)
        assert result.verdict == "skipped"


# ---------------------------------------------------------------------------
# Verdict mapping from JSON flags
# ---------------------------------------------------------------------------

class TestVerdictMapping:
    def setup_method(self):
        self.judge = HarnessJudge()

    def _result(self, overrides: dict) -> JudgeResult:
        data = dict(VALID_JUDGE_JSON)
        data.update(overrides)
        return self.judge._parse_result(json.dumps(data), task_id="vm")

    def test_verdict_fail_when_lob_violation(self):
        r = self._result({
            "lob_violation": {"result": "yes", "evidence": "bad import"},
            "overall_verdict": "fail",
            "fail_reasons": ["lob_violation"],
        })
        assert r.verdict == "fail"
        assert r.lob_violation is True

    def test_verdict_warn_when_duplication_only(self):
        r = self._result({
            "duplication": {"result": "yes", "evidence": "copy-paste"},
            "overall_verdict": "warn",
            "fail_reasons": [],
        })
        assert r.verdict == "warn"
        assert r.duplication is True

    def test_verdict_pass_when_all_clean(self):
        r = self._result({})
        assert r.verdict == "pass"
        assert r.lob_violation is False
        assert r.duplication is False
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestEvaluate hooks/tests/test_judge.py::TestVerdictMapping -v 2>&1 | head -30
```
Expected: failures because `evaluate()` returns `None`

- [ ] **Step 3: Implement `evaluate()`**

Replace `pass` in `evaluate` with:

```python
    def evaluate(self, payload: JudgePayload) -> "JudgeResult":
        try:
            prompt = self._build_prompt(payload)
            result = subprocess.run(
                ["claude", "-p", prompt, "--model", self.model, "--output-format", "text"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return self._parse_result("", task_id=payload.task_id)
            return self._parse_result(result.stdout, task_id=payload.task_id)
        except subprocess.TimeoutExpired:
            return JudgeResult(
                task_id=payload.task_id,
                verdict="skipped",
                lob_violation=False, lob_evidence=None,
                duplication=False, duplication_evidence=None,
                type_contract_violation=False, type_contract_evidence=None,
                unjustified_complexity=False, complexity_evidence=None,
                naming_consistency_score=1.0, naming_evidence=None,
                edge_case_coverage="adequate",
                spec_fulfilled="yes", spec_evidence=None,
                fail_reasons=[], raw_response=None,
            )
        except Exception:
            return JudgeResult(
                task_id=payload.task_id,
                verdict="skipped",
                lob_violation=False, lob_evidence=None,
                duplication=False, duplication_evidence=None,
                type_contract_violation=False, type_contract_evidence=None,
                unjustified_complexity=False, complexity_evidence=None,
                naming_consistency_score=1.0, naming_evidence=None,
                edge_case_coverage="adequate",
                spec_fulfilled="yes", spec_evidence=None,
                fail_reasons=[], raw_response=None,
            )
```

Also add `import subprocess` at the top of `judge/evaluator.py` (already there from the initial stub).

- [ ] **Step 4: Run to verify tests pass**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestEvaluate hooks/tests/test_judge.py::TestVerdictMapping -v
```
Expected: `9 passed`

- [ ] **Step 5: Run all judge tests to check no regressions**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py -v
```
Expected: `18 passed` (2 data + 5 prompt + 7 parse + 6 evaluate + 3 mapping — adjust if counts vary)

- [ ] **Step 6: Commit**

```bash
cd /Users/vini/.claude/devflow && git add judge/evaluator.py hooks/tests/test_judge.py
git commit -m "feat(judge): implement evaluate() with subprocess timeout and never-raises guarantee"
```

---

## Task 5: JudgeRouter

**Files:**
- Create: `judge/router.py`
- Modify: `hooks/tests/test_judge.py` — add `TestJudgeRouter`

- [ ] **Step 1: Write failing tests for JudgeRouter**

Add to `hooks/tests/test_judge.py`:

```python
# ---------------------------------------------------------------------------
# JudgeRouter
# ---------------------------------------------------------------------------

def _make_result(verdict: str, task_id: str = "r1") -> JudgeResult:
    """Helper: build a JudgeResult with a given verdict."""
    return JudgeResult(
        task_id=task_id, verdict=verdict,
        lob_violation=(verdict == "fail"), lob_evidence=None,
        duplication=False, duplication_evidence=None,
        type_contract_violation=False, type_contract_evidence=None,
        unjustified_complexity=False, complexity_evidence=None,
        naming_consistency_score=1.0, naming_evidence=None,
        edge_case_coverage="adequate", spec_fulfilled="yes",
        spec_evidence=None, fail_reasons=["lob_violation"] if verdict == "fail" else [],
        raw_response=None,
    )


class TestJudgeRouter:
    def setup_method(self):
        self.router = JudgeRouter()

    # should_run
    def test_should_run_vibe_is_false(self):
        assert self.router.should_run("vibe") is False

    def test_should_run_standard_is_true(self):
        assert self.router.should_run("standard") is True

    def test_should_run_strict_is_true(self):
        assert self.router.should_run("strict") is True

    def test_should_run_human_review_is_true(self):
        assert self.router.should_run("human_review") is True

    # should_block
    def test_should_block_strict_fail(self):
        assert self.router.should_block("strict", _make_result("fail")) is True

    def test_should_not_block_strict_warn(self):
        assert self.router.should_block("strict", _make_result("warn")) is False

    def test_should_not_block_standard_fail(self):
        assert self.router.should_block("standard", _make_result("fail")) is False

    def test_should_block_human_review_pass(self):
        assert self.router.should_block("human_review", _make_result("pass")) is True

    def test_should_block_human_review_fail(self):
        assert self.router.should_block("human_review", _make_result("fail")) is True

    # handle
    def test_handle_writes_judge_result_json(self, tmp_path):
        result = _make_result("pass")
        self.router.handle("standard", result, tmp_path)
        out = json.loads((tmp_path / "judge-result.json").read_text())
        assert out["verdict"] == "pass"

    def test_handle_returns_0_for_standard_fail(self, tmp_path):
        result = _make_result("fail")
        code = self.router.handle("standard", result, tmp_path)
        assert code == 0

    def test_handle_returns_1_for_strict_fail(self, tmp_path):
        result = _make_result("fail")
        code = self.router.handle("strict", result, tmp_path)
        assert code == 1

    def test_handle_writes_pending_review_for_human_review(self, tmp_path):
        result = _make_result("pass")
        self.router.handle("human_review", result, tmp_path)
        pending_dir = tmp_path / "pending_reviews"
        assert pending_dir.exists()
        files = list(pending_dir.iterdir())
        assert len(files) == 1

    def test_handle_prints_summary(self, tmp_path, capsys):
        result = _make_result("fail")
        self.router.handle("strict", result, tmp_path)
        out = capsys.readouterr().out
        assert "[devflow:judge]" in out
        assert "verdict=FAIL" in out
        assert "oversight=STRICT" in out
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestJudgeRouter -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'JudgeRouter' from 'judge.router'` (file doesn't exist)

- [ ] **Step 3: Create `judge/router.py`**

```python
# judge/router.py
"""
JudgeRouter — maps oversight_level to blocking behaviour.

Writes evaluation results to state_dir.
"""
from __future__ import annotations

import json
from pathlib import Path

from judge.evaluator import JudgeResult


class JudgeRouter:

    def should_run(self, oversight_level: str) -> bool:
        return oversight_level in ("standard", "strict", "human_review")

    def should_block(self, oversight_level: str, result: JudgeResult) -> bool:
        if oversight_level == "human_review":
            return True
        if oversight_level == "strict" and result.verdict == "fail":
            return True
        return False

    def handle(
        self,
        oversight_level: str,
        result: JudgeResult,
        state_dir: Path,
    ) -> int:
        """
        Returns exit code: 0 = allow, 1 = block.
        Always writes judge-result.json to state_dir.
        Writes to pending_reviews/ if human_review.
        """
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)

        # Always write result
        result_data = {
            "verdict": result.verdict,
            "task_id": result.task_id,
            "lob_violation": result.lob_violation,
            "duplication": result.duplication,
            "type_contract_violation": result.type_contract_violation,
            "unjustified_complexity": result.unjustified_complexity,
            "naming_consistency_score": result.naming_consistency_score,
            "edge_case_coverage": result.edge_case_coverage,
            "spec_fulfilled": result.spec_fulfilled,
            "fail_reasons": result.fail_reasons,
            "oversight_level": oversight_level,
        }
        (state_dir / "judge-result.json").write_text(json.dumps(result_data, indent=2))

        # Pending review queue
        if oversight_level == "human_review":
            pending_dir = state_dir / "pending_reviews"
            pending_dir.mkdir(exist_ok=True)
            review_file = pending_dir / f"{result.task_id}.json"
            review_file.write_text(json.dumps(result_data, indent=2))

        # Print summary
        print(
            f"[devflow:judge] verdict={result.verdict.upper()} "
            f"oversight={oversight_level.upper()}"
        )

        return 1 if self.should_block(oversight_level, result) else 0
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestJudgeRouter -v
```
Expected: `15 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow && git add judge/router.py hooks/tests/test_judge.py
git commit -m "feat(judge): implement JudgeRouter with oversight-level blocking and state writes"
```

---

## Task 6: post_task_judge.py hook

**Files:**
- Create: `hooks/post_task_judge.py`
- Modify: `hooks/tests/test_judge.py` — add `TestPostTaskJudgeHook`

- [ ] **Step 1: Write failing tests for the hook**

Add to `hooks/tests/test_judge.py`:

```python
# ---------------------------------------------------------------------------
# post_task_judge hook
# ---------------------------------------------------------------------------

class TestPostTaskJudgeHook:
    """Tests for the Stop hook that orchestrates judge evaluation."""

    def _write_risk_profile(self, tmp_path: Path, oversight_level: str) -> None:
        (tmp_path / "risk-profile.json").write_text(json.dumps({
            "oversight_level": oversight_level,
            "probability": 0.3,
            "impact": 0.8,
            "detectability": 0.5,
        }))

    def test_reads_oversight_level_from_risk_profile(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import post_task_judge
        self._write_risk_profile(tmp_path, "strict")
        with patch.object(post_task_judge, "_get_state_dir", return_value=tmp_path), \
             patch.object(post_task_judge, "_get_diff", return_value=""), \
             patch("post_task_judge.HarnessJudge") as mock_judge_cls, \
             patch("post_task_judge.JudgeRouter") as mock_router_cls:
            mock_judge = MagicMock()
            mock_judge.evaluate.return_value = _make_result("pass")
            mock_judge_cls.return_value = mock_judge
            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router.handle.return_value = 0
            mock_router_cls.return_value = mock_router
            post_task_judge.run(tmp_path)
        mock_router.should_run.assert_called_once_with("strict")

    def test_skips_when_vibe(self, tmp_path, capsys):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import post_task_judge
        self._write_risk_profile(tmp_path, "vibe")
        with patch.object(post_task_judge, "_get_state_dir", return_value=tmp_path):
            code = post_task_judge.run(tmp_path)
        out = capsys.readouterr().out
        assert code == 0
        assert "skipped (vibe)" in out

    def test_calls_evaluate_with_correct_task_id(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import post_task_judge
        self._write_risk_profile(tmp_path, "standard")
        with patch.object(post_task_judge, "_get_state_dir", return_value=tmp_path), \
             patch.object(post_task_judge, "_get_diff", return_value="diff content"), \
             patch("post_task_judge.HarnessJudge") as mock_judge_cls, \
             patch("post_task_judge.JudgeRouter") as mock_router_cls, \
             patch("post_task_judge.get_session_id", return_value="test-session-123"):
            mock_judge = MagicMock()
            mock_judge.evaluate.return_value = _make_result("pass", "test-session-123")
            mock_judge_cls.return_value = mock_judge
            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router.handle.return_value = 0
            mock_router_cls.return_value = mock_router
            post_task_judge.run(tmp_path)
        call_kwargs = mock_judge.evaluate.call_args[0][0]
        assert call_kwargs.task_id == "test-session-123"
        assert call_kwargs.diff == "diff content"

    def test_updates_telemetry_store(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import post_task_judge
        self._write_risk_profile(tmp_path, "standard")
        mock_store = MagicMock()
        with patch.object(post_task_judge, "_get_state_dir", return_value=tmp_path), \
             patch.object(post_task_judge, "_get_diff", return_value=""), \
             patch("post_task_judge.HarnessJudge") as mock_judge_cls, \
             patch("post_task_judge.JudgeRouter") as mock_router_cls, \
             patch("post_task_judge.TelemetryStore", return_value=mock_store):
            mock_judge = MagicMock()
            mock_judge.evaluate.return_value = _make_result("warn")
            mock_judge_cls.return_value = mock_judge
            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router.handle.return_value = 0
            mock_router_cls.return_value = mock_router
            post_task_judge.run(tmp_path)
        mock_store.record.assert_called_once()
        record_payload = mock_store.record.call_args[0][0]
        assert record_payload["judge_verdict"] == "warn"

    def test_defaults_to_standard_when_no_risk_profile(self, tmp_path, capsys):
        """Missing risk-profile.json should not crash — default to standard."""
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import post_task_judge
        # Do NOT write risk-profile.json
        with patch.object(post_task_judge, "_get_state_dir", return_value=tmp_path), \
             patch.object(post_task_judge, "_get_diff", return_value=""), \
             patch("post_task_judge.HarnessJudge") as mock_judge_cls, \
             patch("post_task_judge.JudgeRouter") as mock_router_cls:
            mock_judge = MagicMock()
            mock_judge.evaluate.return_value = _make_result("pass")
            mock_judge_cls.return_value = mock_judge
            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router.handle.return_value = 0
            mock_router_cls.return_value = mock_router
            code = post_task_judge.run(tmp_path)
        assert code == 0
        mock_router.should_run.assert_called_once_with("standard")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestPostTaskJudgeHook -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'post_task_judge'`

- [ ] **Step 3: Create `hooks/post_task_judge.py`**

```python
# hooks/post_task_judge.py
"""
Stop hook — LLM-as-judge orchestrator.

Runs after a task completes. Reads oversight_level from risk-profile.json,
evaluates the diff via HarnessJudge, routes result through JudgeRouter,
updates TelemetryStore, and exits with the router's exit code.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_DEVFLOW_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from _util import get_session_id, get_state_dir
from judge.evaluator import HarnessJudge, JudgePayload
from judge.router import JudgeRouter

try:
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]


def _get_state_dir() -> Path:
    return get_state_dir()


def _get_diff() -> str:
    """Return git diff HEAD~1, falling back to git diff (unstaged)."""
    for cmd in [["git", "diff", "HEAD~1"], ["git", "diff"]]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.stdout.strip():
                return result.stdout
        except Exception:
            pass
    return ""


def _read_spec(state_dir: Path) -> str:
    spec_path = state_dir / "active-spec.json"
    if not spec_path.exists():
        return ""
    try:
        spec = json.loads(spec_path.read_text())
        plan_path = spec.get("plan_path", "")
        # If plan_path is a file path, try to read it
        if plan_path and not plan_path.startswith("/"):
            candidate = _DEVFLOW_ROOT / plan_path
            if candidate.exists():
                return candidate.read_text()
        return str(plan_path)
    except (json.JSONDecodeError, OSError):
        return ""


def _read_harness_rules() -> list[str]:
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    if not claude_md.exists():
        return []
    try:
        lines = claude_md.read_text().splitlines()[:50]
        return [l for l in lines if l.strip()]
    except OSError:
        return []


def _read_existing_code(diff: str) -> str:
    """Read first 100 lines of each file modified in the diff."""
    parts = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            file_path = line[6:].strip()
            candidate = Path(file_path)
            if not candidate.exists():
                candidate = Path.cwd() / file_path
            if candidate.exists():
                try:
                    content_lines = candidate.read_text().splitlines()[:100]
                    parts.append(f"# {file_path}\n" + "\n".join(content_lines))
                except OSError:
                    pass
    return "\n\n".join(parts)


def _read_feature_path(state_dir: Path) -> str:
    profile_path = state_dir / "project-profile.json"
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text())
            return profile.get("feature_path") or "."
        except (json.JSONDecodeError, OSError):
            pass
    return "."


def run(state_dir: Path) -> int:
    # Read oversight_level
    risk_path = state_dir / "risk-profile.json"
    oversight_level = "standard"
    if risk_path.exists():
        try:
            risk = json.loads(risk_path.read_text())
            oversight_level = risk.get("oversight_level", "standard")
        except (json.JSONDecodeError, OSError):
            pass

    router = JudgeRouter()

    if not router.should_run(oversight_level):
        print("[devflow:judge] skipped (vibe)")
        return 0

    # Build payload
    diff = _get_diff()
    task_id = get_session_id()

    payload = JudgePayload(
        diff=diff,
        spec=_read_spec(state_dir),
        harness_rules=_read_harness_rules(),
        existing_code=_read_existing_code(diff),
        feature_path=_read_feature_path(state_dir),
        task_id=task_id,
    )

    # Evaluate
    judge = HarnessJudge()
    result = judge.evaluate(payload)

    # Route
    exit_code = router.handle(oversight_level, result, state_dir)

    # Telemetry
    store_cls = TelemetryStore
    if store_cls is not None:
        try:
            store = store_cls()
            store.record({
                "task_id": task_id,
                "judge_verdict": result.verdict,
                "judge_categories_failed": json.dumps(result.fail_reasons),
                "lob_violations": 1 if result.lob_violation else 0,
                "duplication_detected": result.duplication,
                "type_contract_violations": 1 if result.type_contract_violation else 0,
                "unjustified_complexity": result.unjustified_complexity,
                "naming_consistency_score": result.naming_consistency_score,
                "edge_case_coverage": result.edge_case_coverage,
            })
        except Exception:
            pass

    return exit_code


def main() -> int:
    try:
        return run(_get_state_dir())
    except Exception as exc:
        print(f"[devflow:judge] error: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py::TestPostTaskJudgeHook -v
```
Expected: `5 passed`

- [ ] **Step 5: Run full judge test suite**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_judge.py -v
```
Expected: all tests passing (approximately 37 tests total)

- [ ] **Step 6: Commit**

```bash
cd /Users/vini/.claude/devflow && git add hooks/post_task_judge.py hooks/tests/test_judge.py
git commit -m "feat(judge): implement post_task_judge Stop hook with telemetry integration"
```

---

## Task 7: Ground truth calibration dataset

**Files:**
- Create: `judge/calibration/pass_001.json`
- Create: `judge/calibration/pass_002.json`
- Create: `judge/calibration/warn_001.json`
- Create: `judge/calibration/fail_001.json`
- Create: `judge/calibration/fail_002.json`

These are based on real commits from devflow's git history.

- [ ] **Step 1: Create `judge/calibration/pass_001.json`**

Based on commit `cbfe3b3` — targeted bugfix, single file, no LoB violation, no duplication.

```json
{
  "diff": "diff --git a/telemetry/store.py b/telemetry/store.py\n--- a/telemetry/store.py\n+++ b/telemetry/store.py\n@@ -8,6 +8,7 @@ from __future__ import annotations\n import sqlite3\n import threading\n+from contextlib import closing\n from datetime import datetime, timezone, timedelta\n@@ -86,7 +87,7 @@ class TelemetryStore:\n     def _init_schema(self):\n         with self._lock:\n-            with self._connect() as conn:\n+            with closing(self._connect()) as conn:\n                 conn.execute(_CREATE_TABLE)\n                 conn.commit()\n@@ -107,7 +108,7 @@ class TelemetryStore:\n         with self._lock:\n-            with self._connect() as conn:\n+            with closing(self._connect()) as conn:\n                 conn.execute(sql, values)",
  "spec": "Fix SQLite connection leak: close connections explicitly via contextlib.closing in TelemetryStore. Applies to _init_schema, record, get_by_category, get_recent, get_failure_patterns, get_context_anxiety_cases.",
  "harness_rules": [
    "No TODO without associated issue",
    "Atomic, descriptive commits",
    "File length limits: warn at 400, block at 600"
  ],
  "existing_code": "class TelemetryStore:\n    def _connect(self) -> sqlite3.Connection:\n        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)\n        conn.row_factory = sqlite3.Row\n        return conn",
  "feature_path": "telemetry/",
  "expected_verdict": "pass",
  "expected_flags": {
    "lob_violation": false,
    "duplication": false,
    "type_contract_violation": false,
    "unjustified_complexity": false,
    "spec_fulfilled": "yes"
  },
  "notes": "Single-file, scoped bugfix. Adds contextlib.closing import and wraps all connection usages. No new abstractions, no cross-boundary imports. Classic pass case."
}
```

- [ ] **Step 2: Create `judge/calibration/pass_002.json`**

Based on commit `56a22c0` — new feature with full test coverage, no duplication.

```json
{
  "diff": "diff --git a/telemetry/__init__.py b/telemetry/__init__.py\nnew file mode 100644\ndiff --git a/telemetry/store.py b/telemetry/store.py\nnew file mode 100644\n+++ b/telemetry/store.py\n@@ -0,0 +1,30 @@\n+class TelemetryStore:\n+    def __init__(self, db_path=None):\n+        self._db_path = Path(db_path) if db_path else _DEFAULT_DB\n+        self._lock = threading.Lock()\n+        self._init_schema()\n+    def record(self, payload: dict) -> None:\n+        values = {col: payload.get(col) for col in _COLUMNS}\n+        ...\n+diff --git a/hooks/tests/test_telemetry_store.py b/hooks/tests/test_telemetry_store.py\nnew file mode 100644\n+++ b/hooks/tests/test_telemetry_store.py\n@@ -0,0 +1,100 @@\n+class TestTelemetryStoreSchema:\n+    def test_schema_has_all_columns(self, tmp_path): ...\n+class TestRecord:\n+    def test_insert_and_retrieve(self, tmp_path): ...",
  "spec": "Add TelemetryStore SQLite persistence layer. Schema: task_executions with 31 columns. API: record() upsert, get_by_category(), get_recent(), get_failure_patterns(), get_context_anxiety_cases(), summary_stats(). Thread-safe writes via Lock. 14 tests.",
  "harness_rules": [
    "TDD: RED -> GREEN -> REFACTOR -> COMMIT",
    "No TODO without associated issue",
    "File length limits: warn at 400, block at 600"
  ],
  "existing_code": "# telemetry/ directory did not exist before this commit",
  "feature_path": "telemetry/",
  "expected_verdict": "pass",
  "expected_flags": {
    "lob_violation": false,
    "duplication": false,
    "type_contract_violation": false,
    "unjustified_complexity": false,
    "spec_fulfilled": "yes"
  },
  "notes": "New package, new feature, tests included, stays within telemetry/ boundary. No cross-boundary imports from other devflow modules. Good pass example for a feature addition."
}
```

- [ ] **Step 3: Create `judge/calibration/warn_001.json`**

Hypothetical: fix is correct but missing edge cases in error handling.

```json
{
  "diff": "diff --git a/hooks/task_telemetry.py b/hooks/task_telemetry.py\n--- a/hooks/task_telemetry.py\n+++ b/hooks/task_telemetry.py\n@@ -305,7 +305,12 @@ def main():\n-    if session_id in existing_ids:\n-        return 0\n+    # Replace stale record with fresh parse\n+    records = [r for r in records if r.get('session_id') != session_id]\n+    records.append(new_record)\n+    out_path.write_text('\\n'.join(json.dumps(r) for r in records))",
  "spec": "Fix task_telemetry sessions stuck at PENDING. Change deduplication from skip-if-exists to replace-if-exists so that later stop hook fires update the record with full phase data.",
  "harness_rules": [
    "No TODO without associated issue",
    "Atomic, descriptive commits"
  ],
  "existing_code": "def main():\n    existing_ids = {r.get('session_id') for r in records}\n    if session_id in existing_ids:\n        return 0",
  "feature_path": "hooks/",
  "expected_verdict": "warn",
  "expected_flags": {
    "lob_violation": false,
    "duplication": false,
    "type_contract_violation": false,
    "unjustified_complexity": false,
    "spec_fulfilled": "partial",
    "edge_case_coverage": "minimal"
  },
  "notes": "The fix is correct for the primary case but doesn't cover concurrent writes (two sessions running simultaneously), empty JSONL file on first write, or malformed JSON lines in the existing file. Missing edge cases → warn."
}
```

- [ ] **Step 4: Create `judge/calibration/fail_001.json`**

LoB violation: hooks module importing from a cross-boundary service.

```json
{
  "diff": "diff --git a/hooks/file_checker.py b/hooks/file_checker.py\n--- a/hooks/file_checker.py\n+++ b/hooks/file_checker.py\n@@ -1,5 +1,7 @@\n+from telemetry.store import TelemetryStore\n+from risk.profiler import TaskRiskProfiler\n+from judge.evaluator import HarnessJudge\n ...\n def check_file(path):\n+    profiler = TaskRiskProfiler()\n+    profile = profiler.profile({})\n+    if profile.oversight_level == 'strict':\n+        judge = HarnessJudge()\n+        result = judge.evaluate(payload)\n     _run_linter(path)",
  "spec": "Add linting to file_checker that skips slow checks when oversight_level is vibe.",
  "harness_rules": [
    "File length limits: warn at 400, block at 600",
    "Design System first: consult existing components before creating new ones"
  ],
  "existing_code": "def check_file(path):\n    _run_linter(path)\n    _check_length(path)",
  "feature_path": "hooks/",
  "expected_verdict": "fail",
  "expected_flags": {
    "lob_violation": true,
    "duplication": false,
    "type_contract_violation": false,
    "unjustified_complexity": false,
    "spec_fulfilled": "yes"
  },
  "notes": "file_checker.py (hooks/) imports HarnessJudge from judge/ and TaskRiskProfiler from risk/ inside a function that previously had no such dependency. This creates a circular dependency risk (judge/ Stop hook calls file_checker logic) and violates the boundary between hooks and evaluation modules. Clear LoB violation."
}
```

- [ ] **Step 5: Create `judge/calibration/fail_002.json`**

Unjustified complexity: over-engineering a simple data read.

```json
{
  "diff": "diff --git a/hooks/_util.py b/hooks/_util.py\n--- a/hooks/_util.py\n+++ b/hooks/_util.py\n@@ -1,3 +1,40 @@\n+class ConfigLoader:\n+    _instance = None\n+    _cache = {}\n+    def __new__(cls):\n+        if cls._instance is None:\n+            cls._instance = super().__new__(cls)\n+        return cls._instance\n+    def load(self, key, transformer=None, validator=None, cache_ttl=300):\n+        if key in self._cache:\n+            cached_at, value = self._cache[key]\n+            if time.time() - cached_at < cache_ttl:\n+                return value\n+        raw = self._read_raw(key)\n+        if transformer:\n+            raw = transformer(raw)\n+        if validator and not validator(raw):\n+            raise ValueError(f'Invalid config: {key}')\n+        self._cache[key] = (time.time(), raw)\n+        return raw\n+    def _read_raw(self, key):\n+        ...\n+\n def load_devflow_config(project_root=None):\n-    config = dict(defaults)\n-    if DEVFLOW_CONFIG_GLOBAL.exists():\n-        config.update(json.loads(DEVFLOW_CONFIG_GLOBAL.read_text()))\n-    return config\n+    loader = ConfigLoader()\n+    return loader.load('devflow_config', transformer=_merge_defaults, validator=_validate_config)",
  "spec": "Refactor load_devflow_config to cache the config so repeated calls in the same session don't re-read the file.",
  "harness_rules": [
    "Don't add features beyond what was asked",
    "Three similar lines is better than a premature abstraction",
    "No TODO without associated issue"
  ],
  "existing_code": "def load_devflow_config(project_root=None):\n    config = dict(defaults)\n    if DEVFLOW_CONFIG_GLOBAL.exists():\n        config.update(json.loads(DEVFLOW_CONFIG_GLOBAL.read_text()))\n    return config",
  "feature_path": "hooks/",
  "expected_verdict": "fail",
  "expected_flags": {
    "lob_violation": false,
    "duplication": false,
    "type_contract_violation": false,
    "unjustified_complexity": true,
    "spec_fulfilled": "partial"
  },
  "notes": "The spec asked for simple caching. The diff introduces a Singleton ConfigLoader with TTL, transformer pipeline, validator injection, and a two-level cache. A module-level dict or @lru_cache would have sufficed. Unjustified complexity for what is a config file read that happens once per session."
}
```

- [ ] **Step 6: Commit**

```bash
cd /Users/vini/.claude/devflow && git add judge/calibration/
git commit -m "feat(judge): add 5 ground truth calibration examples (2 pass, 1 warn, 2 fail)"
```

---

## Task 8: Full test suite validation + documentation

**Files:**
- Modify: `docs/audit-20260331.md`

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/ -q
```
Expected: all tests pass, total > 366

- [ ] **Step 2: Record exact count**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/ -q 2>&1 | tail -3
```
Note the number of tests passing.

- [ ] **Step 3: Smoke test the hook**

```bash
cd /Users/vini/.claude/devflow && python3.13 hooks/post_task_judge.py
```
Expected output: `[devflow:judge] verdict=... oversight=...` or `[devflow:judge] skipped (vibe)`

- [ ] **Step 4: Append Prompt 3 section to audit doc**

Append to `docs/audit-20260331.md`:

```markdown
### Prompt 3: LLM-as-judge — N tests added, 366 → M total (`2026-03-31`)

**Files created:**
- `judge/__init__.py` — Python package marker
- `judge/evaluator.py` — `JudgePayload`, `JudgeResult` dataclasses + `HarnessJudge`: `_build_prompt()` (rubric + system instruction), `_parse_result()` (JSON fence stripping, skipped fallback), `evaluate()` (subprocess call to `claude -p`, 30s timeout, never raises)
- `judge/router.py` — `JudgeRouter`: `should_run()` (vibe skips), `should_block()` (strict+fail or human_review always blocks), `handle()` (writes judge-result.json, pending_reviews/ queue, prints summary, returns exit code)
- `judge/calibration/` — 5 ground truth examples: pass_001 (targeted bugfix), pass_002 (feature + tests), warn_001 (missing edge cases), fail_001 (LoB violation), fail_002 (unjustified complexity)
- `hooks/post_task_judge.py` — Stop hook: reads risk-profile.json → builds JudgePayload → HarnessJudge.evaluate() → JudgeRouter.handle() → TelemetryStore.record() → exits with router code

**Tests added (N):**
- `TestDataClasses` (2): JudgePayload and JudgeResult field validation
- `TestBuildPrompt` (5): diff, spec, harness_rules, "Respond ONLY with valid JSON", feature_path in output
- `TestParseResult` (7): valid JSON, fence stripping (json/bare), invalid → skipped, empty → skipped, fail verdict, raw_response preserved
- `TestEvaluate` (6): valid response → JudgeResult, timeout → skipped, any exception → skipped, empty payload, subprocess called with model, nonzero exit → skipped
- `TestVerdictMapping` (3): fail when lob_violation, warn when duplication only, pass when all clean
- `TestJudgeRouter` (15): should_run ×4, should_block ×5, handle writes/prints/returns ×6
- `TestPostTaskJudgeHook` (5): reads oversight_level, skips on vibe, correct task_id in payload, updates TelemetryStore, defaults to standard on missing file

**hooks/tests/ baseline:** 366 → M (N net added)
**Smoke test:** `python3.13 hooks/post_task_judge.py` → prints verdict line ✓
**Regressions:** 0
```

- [ ] **Step 5: Final commit**

```bash
cd /Users/vini/.claude/devflow && git add docs/audit-20260331.md
git commit -m "docs: record Prompt 3 LLM-as-judge in audit log"
```

---

## Verification Checklist

- [ ] `python3.13 -m pytest hooks/tests/ -q` — all tests pass, count > 366
- [ ] `python3.13 hooks/post_task_judge.py` — prints `[devflow:judge]` line, exits 0
- [ ] `judge/__init__.py` exists and is empty
- [ ] `judge/calibration/` contains exactly 5 JSON files
- [ ] `docs/audit-20260331.md` has Prompt 3 section with actual test counts
