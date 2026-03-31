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

        if oversight_level == "human_review":
            pending_dir = state_dir / "pending_reviews"
            pending_dir.mkdir(exist_ok=True)
            (pending_dir / f"{result.task_id}.json").write_text(
                json.dumps(result_data, indent=2)
            )

        print(
            f"[devflow:judge] verdict={result.verdict.upper()} "
            f"oversight={oversight_level.upper()}"
        )

        return 1 if self.should_block(oversight_level, result) else 0
