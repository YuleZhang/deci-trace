"""Decision Proxy with rule, retrieval, and retrieval+LLM baselines."""

from __future__ import annotations

import re
import time
from typing import Callable

from decitrace.core.models import RiskLevel
from decitrace.core.storage import Store
from decitrace.decision.models import DecisionRequest, Recommendation
from decitrace.decision.providers import Provider, ProviderUnavailable
from decitrace.decision.retrieval import retrieve_cases
from decitrace.decision.rules import match_rules
from decitrace.decision.similarity import choices_agree, similarity

_HIGH = re.compile(r"(?:生产|线上|deploy|删除|delete|凭证|credential|secret|安全|security|migration|支付)", re.I)
_MEDIUM = re.compile(r"(?:架构|依赖|dependency|API|性能|performance|schema|数据库|兼容|breaking)", re.I)


class DecisionProxy:
    def __init__(
        self,
        store: Store,
        *,
        include_pending: bool = False,
        provider: Provider | None = None,
    ):
        self.store = store
        self.include_pending = include_pending
        self.provider = provider

    def decide(self, request: DecisionRequest, baseline: str = "case") -> Recommendation:
        started = time.perf_counter()
        risk = request.risk if request.risk != RiskLevel.UNKNOWN else _infer_risk(request)
        if baseline == "rule":
            result = self._rule(request, risk)
        elif baseline == "case":
            result = self._case(request, risk)
        elif baseline == "case_llm":
            result = self._case_llm(request, risk)
        else:
            raise ValueError(f"unknown baseline: {baseline}")
        result.latency_ms = (time.perf_counter() - started) * 1000
        return result

    def _rule(self, request: DecisionRequest, risk: RiskLevel) -> Recommendation:
        rules = match_rules(self.store, request)
        if risk == RiskLevel.HIGH:
            return _abstain("rule", risk, "high_risk_requires_user", rules=rules)
        if not rules or rules[0].score < 0.08:
            return _abstain("rule", risk, "insufficient_rule_evidence", rules=rules)
        if _rule_conflict(rules):
            return _abstain("rule", risk, "conflicting_rules", rules=rules)
        if risk == RiskLevel.MEDIUM and (len(rules) < 2 or not choices_agree(rules[0].choice, rules[1].choice)):
            return _abstain("rule", risk, "medium_risk_needs_two_consistent_rules", rules=rules)
        choice = _map_choice(rules[0].choice, request.options)
        return Recommendation(
            baseline="rule", action="answer", recommended_choice=choice,
            rationale="Matched an explicit, reviewed personal rule.",
            rules=rules, confidence=min(0.95, 0.55 + rules[0].score),
            evidence_sufficiency="sufficient", risk=risk, latency_ms=0,
        )

    def _case(self, request: DecisionRequest, risk: RiskLevel) -> Recommendation:
        cases = retrieve_cases(self.store, request, include_pending=self.include_pending)
        if risk == RiskLevel.HIGH:
            return _abstain("case", risk, "high_risk_requires_user", cases=cases)
        reason = _case_gate(cases, risk)
        if reason:
            return _abstain("case", risk, reason, cases=cases)
        choice = _map_choice(cases[0].choice or "", request.options)
        return Recommendation(
            baseline="case", action="answer", recommended_choice=choice,
            rationale="Top historical user decision is sufficiently similar and non-conflicting.",
            cases=cases, confidence=min(0.92, 0.5 + cases[0].score),
            evidence_sufficiency="sufficient", risk=risk, latency_ms=0,
        )

    def _case_llm(self, request: DecisionRequest, risk: RiskLevel) -> Recommendation:
        cases = retrieve_cases(self.store, request, include_pending=self.include_pending)
        if risk == RiskLevel.HIGH:
            return _abstain("case_llm", risk, "high_risk_requires_user", cases=cases)
        reason = _case_gate(cases, risk)
        if reason:
            return _abstain("case_llm", risk, reason, cases=cases)
        if self.provider is None:
            return _abstain("case_llm", risk, "llm_disabled", cases=cases)
        try:
            answer = self.provider.infer(request, cases)
        except ProviderUnavailable as exc:
            return _abstain("case_llm", risk, str(exc), cases=cases)
        if answer.confidence < 0.55:
            result = _abstain("case_llm", risk, "llm_low_confidence", cases=cases)
            result.input_tokens = answer.input_tokens
            result.output_tokens = answer.output_tokens
            return result
        return Recommendation(
            baseline="case_llm", action="answer",
            recommended_choice=_map_choice(answer.choice, request.options),
            rationale=answer.rationale, cases=cases, confidence=answer.confidence,
            evidence_sufficiency="sufficient", risk=risk, latency_ms=0,
            input_tokens=answer.input_tokens, output_tokens=answer.output_tokens,
        )


def _case_gate(cases: list, risk: RiskLevel) -> str | None:
    if not cases or cases[0].score < 0.06:
        return "insufficient_case_evidence"
    if len(cases) > 1 and abs(cases[0].score - cases[1].score) <= 0.03:
        if not choices_agree(cases[0].choice, cases[1].choice):
            return "conflicting_cases"
    if risk == RiskLevel.MEDIUM:
        if len(cases) < 2 or cases[0].score < 0.1 or not choices_agree(cases[0].choice, cases[1].choice):
            return "medium_risk_needs_two_consistent_cases"
    return None


def _rule_conflict(rules: list) -> bool:
    return (len(rules) > 1 and abs(rules[0].score - rules[1].score) <= 0.03 and
            not choices_agree(rules[0].choice, rules[1].choice))


def _map_choice(choice: str, options: list[str]) -> str:
    if not options:
        return choice
    scored = [(similarity(choice, option), option) for option in options]
    score, option = max(scored, key=lambda item: item[0])
    return option if score >= 0.2 else choice


def _infer_risk(request: DecisionRequest) -> RiskLevel:
    text = "\n".join([request.question, request.project_context or "", *request.constraints])
    if _HIGH.search(text):
        return RiskLevel.HIGH
    if _MEDIUM.search(text):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _abstain(
    baseline: str,
    risk: RiskLevel,
    reason: str,
    *,
    cases: list | None = None,
    rules: list | None = None,
) -> Recommendation:
    return Recommendation(
        baseline=baseline, action="abstain", rationale="User confirmation is required.",
        cases=cases or [], rules=rules or [], confidence=0,
        evidence_sufficiency="insufficient", risk=risk,
        abstain_reason=reason, latency_ms=0,
    )
