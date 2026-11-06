from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from decitrace.core.models import (
    DecisionAttribution,
    DecisionEpisode,
    EpistemicStatus,
    EvidenceRef,
    NormalizedBundle,
    RiskLevel,
    Session,
    SourceTool,
)
from decitrace.core.storage import Store
from decitrace.decision.models import DecisionRequest
from decitrace.decision.providers import ProviderResult
from decitrace.decision.proxy import DecisionProxy
from decitrace.decision.rules import build_rules
from decitrace.evaluation.replay import ReplayEvaluator


class FakeProvider:
    def infer(self, request, cases):
        return ProviderResult("keep SQLite", "Historical local-first preference.", 0.8, 10, 5)


def _store(tmp_path: Path, choices: list[str]) -> Store:
    source = tmp_path / "history.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    store = Store(tmp_path / "db.sqlite3")
    session = Session(
        id="codex:s", source=SourceTool.CODEX, source_path=str(source),
        source_hash="a" * 64, import_batch="b",
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    store.save_bundle(
        NormalizedBundle(session=session), source, str(source.resolve()),
        source.stat().st_size, source.stat().st_mtime_ns,
    )
    for index, choice in enumerate(choices):
        evidence = EvidenceRef(
            source_path=str(source), source_hash="a" * 64,
            line_start=index + 1, line_end=index + 1,
            raw_event_type="user", session_id="s",
        )
        store.upsert_decision(DecisionEpisode(
            id=f"d{index}", session_id=session.id,
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
            question="local first database choice SQLite service",
            choice=choice, evidence=[evidence], confidence=0.9,
            attribution=DecisionAttribution.EXPLICIT_USER,
            epistemic_status=EpistemicStatus.STATEMENT,
            risk=RiskLevel.LOW, review_status="accepted",
        ))
    return store


def test_proxy_answers_consistent_cases_and_abstains_high_risk(tmp_path):
    store = _store(tmp_path, ["keep SQLite", "keep SQLite"])
    try:
        build_rules(store)
        proxy = DecisionProxy(store, provider=FakeProvider())
        request = DecisionRequest(
            question="local first database choice",
            before=datetime(2025, 1, 10, tzinfo=timezone.utc),
        )
        case = proxy.decide(request, "case")
        assert case.action == "answer"
        assert case.recommended_choice == "keep SQLite"
        llm = proxy.decide(request, "case_llm")
        assert llm.action == "answer"
        assert (llm.input_tokens, llm.output_tokens) == (10, 5)
        high = proxy.decide(DecisionRequest(
            question="deploy production database", risk=RiskLevel.HIGH,
        ), "case")
        assert high.action == "abstain"
        assert high.abstain_reason == "high_risk_requires_user"
    finally:
        store.close()


def test_proxy_abstains_on_conflicting_cases(tmp_path):
    store = _store(tmp_path, ["keep SQLite", "add a remote service"])
    try:
        result = DecisionProxy(store).decide(DecisionRequest(
            question="local first database choice",
            before=datetime(2025, 1, 10, tzinfo=timezone.utc),
        ), "case")
        assert result.action == "abstain"
        assert result.abstain_reason == "conflicting_cases"
    finally:
        store.close()


def test_replay_has_no_future_leakage_and_separates_outcomes(tmp_path):
    store = _store(tmp_path, ["keep SQLite", "keep SQLite", "keep SQLite", "keep SQLite"])
    try:
        report = ReplayEvaluator(store, DecisionProxy(store)).run(test_fraction=0.5)
        assert report["status"] == "ok"
        assert report["train_count"] == 2
        for result in report["baselines"].values():
            assert result["future_leakage_violations"] == 0
            assert "observed_outcomes" in result
            assert "preference_agreement_rate" in result
    finally:
        store.close()
