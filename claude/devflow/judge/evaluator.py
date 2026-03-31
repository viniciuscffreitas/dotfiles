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
