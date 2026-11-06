"""Leakage-safe chronological decision replay benchmark."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from decitrace.core.models import DecisionAttribution, DecisionEpisode
from decitrace.core.storage import Store
from decitrace.decision.models import DecisionRequest
from decitrace.decision.proxy import DecisionProxy
from decitrace.decision.rules import build_rules
from decitrace.decision.similarity import choices_agree


class ReplayEvaluator:
    def __init__(self, store: Store, proxy: DecisionProxy):
        self.store = store
        self.proxy = proxy

    def run(
        self,
        *,
        test_fraction: float = 0.3,
        baselines: tuple[str, ...] = ("rule", "case", "case_llm"),
    ) -> dict[str, Any]:
        if not 0 < test_fraction < 1:
            raise ValueError("test_fraction must be between 0 and 1")
        episodes = [
            item for item in self.store.decisions()
            if item.attribution == DecisionAttribution.EXPLICIT_USER
            and item.choice and item.timestamp
            and (self.proxy.include_pending or item.review_status in {"accepted", "corrected"})
        ]
        episodes.sort(key=lambda item: (item.timestamp, item.id))
        if len(episodes) < 2:
            return {
                "status": "insufficient_data", "eligible_decisions": len(episodes),
                "required": 2, "baselines": {},
            }
        split = max(1, min(len(episodes) - 1, int(len(episodes) * (1 - test_fraction))))
        tests = episodes[split:]
        build_rules(self.store, include_pending=self.proxy.include_pending)
        results = {
            baseline: self._evaluate_baseline(baseline, tests)
            for baseline in baselines
        }
        return {
            "status": "ok",
            "split": "chronological",
            "train_count": split,
            "test_count": len(tests),
            "cutoff": tests[0].timestamp.isoformat(),
            "future_leakage_policy": "strictly earlier timestamps only",
            "baselines": results,
        }

    def _evaluate_baseline(self, baseline: str, tests: list[DecisionEpisode]) -> dict[str, Any]:
        answered = correct = citations = valid_citations = 0
        total_latency = 0.0
        input_tokens = output_tokens = 0
        token_unknown = False
        errors: list[dict[str, Any]] = []
        by_risk: dict[str, Counter[str]] = defaultdict(Counter)
        outcomes: Counter[str] = Counter()
        leakage_violations = 0

        for expected in tests:
            request = DecisionRequest(
                question=expected.question,
                project_context=expected.context,
                options=expected.options,
                constraints=expected.constraints,
                risk=expected.risk,
                before=expected.timestamp,
            )
            recommendation = self.proxy.decide(request, baseline)
            total_latency += recommendation.latency_ms
            matched = recommendation.action == "answer" and choices_agree(
                recommendation.recommended_choice, expected.choice
            )
            risk_bucket = by_risk[expected.risk.value]
            risk_bucket["total"] += 1
            outcomes[expected.outcome.status.value if expected.outcome else "unknown"] += 1
            if recommendation.action == "answer":
                answered += 1
                risk_bucket["answered"] += 1
                if matched:
                    correct += 1
                    risk_bucket["correct"] += 1
                else:
                    errors.append({
                        "decision_id": expected.id,
                        "kind": "wrong_auto_answer",
                        "predicted": recommendation.recommended_choice,
                        "expected": expected.choice,
                    })
            else:
                risk_bucket["abstained"] += 1
                errors.append({
                    "decision_id": expected.id,
                    "kind": "abstained",
                    "reason": recommendation.abstain_reason,
                })
            refs = [ref for case in recommendation.cases for ref in case.evidence]
            refs += [ref for rule in recommendation.rules for ref in rule.evidence]
            citations += len(refs)
            valid_citations += sum(
                1 for ref in refs if ref.source_hash and ref.source_path and ref.line_start >= 1
            )
            for case in recommendation.cases:
                if case.timestamp is None or case.timestamp >= expected.timestamp:
                    leakage_violations += 1
            if recommendation.input_tokens is None or recommendation.output_tokens is None:
                token_unknown = True
            else:
                input_tokens += recommendation.input_tokens
                output_tokens += recommendation.output_tokens

        total = len(tests)
        wrong = answered - correct
        return {
            "preference_agreement_rate": correct / total,
            "auto_answer_coverage": answered / total,
            "wrong_auto_answer_rate": wrong / answered if answered else 0.0,
            "abstain_rate": (total - answered) / total,
            "evidence_citation_accuracy": valid_citations / citations if citations else None,
            "future_leakage_violations": leakage_violations,
            "mean_latency_ms": total_latency / total,
            "token_usage": {
                "input": None if token_unknown else input_tokens,
                "output": None if token_unknown else output_tokens,
            },
            "by_risk": {risk: dict(values) for risk, values in by_risk.items()},
            "observed_outcomes": dict(outcomes),
            "note": "Preference agreement and observed execution outcomes are separate measures.",
            "cases": errors,
        }


def write_report(report: dict[str, Any], json_path: Path, markdown_path: Path | None = None) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if markdown_path is None:
        return
    lines = ["# Decision Replay Benchmark", "", f"Status: `{report.get('status')}`", ""]
    if report.get("status") == "ok":
        lines.extend([
            f"- Train decisions: {report['train_count']}",
            f"- Test decisions: {report['test_count']}",
            f"- Cutoff: `{report['cutoff']}`",
            "",
            "| Baseline | Agreement | Coverage | Wrong auto | Abstain | Latency ms |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for name, data in report["baselines"].items():
            lines.append(
                f"| {name} | {data['preference_agreement_rate']:.3f} | "
                f"{data['auto_answer_coverage']:.3f} | {data['wrong_auto_answer_rate']:.3f} | "
                f"{data['abstain_rate']:.3f} | {data['mean_latency_ms']:.2f} |"
            )
        lines.extend(["", "> Agreement reproduces historical preference; it does not prove objective correctness."])
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
