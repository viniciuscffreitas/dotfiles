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
    pass  # implementation follows in Tasks 2-4
