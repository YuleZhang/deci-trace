"""Personal rule materialization from reviewed explicit decisions."""

from __future__ import annotations

from pathlib import Path
import json

from decitrace.core.models import DecisionAttribution, PersonalRule
from decitrace.core.storage import Store
from decitrace.core.util import stable_id
from decitrace.decision.models import DecisionRequest, RuleMatch
from decitrace.decision.similarity import similarity


def build_rules(store: Store, include_pending: bool = False) -> dict[str, int]:
    store.clear_rules()
    created = 0
    skipped = 0
    for decision in store.decisions():
        allowed = decision.review_status == "accepted" or (
            include_pending and decision.review_status in {"pending", "corrected"}
        )
        if not allowed or decision.attribution != DecisionAttribution.EXPLICIT_USER or not decision.choice:
            skipped += 1
            continue
        condition = "\n".join(filter(None, [decision.question, decision.context, *decision.constraints]))
        rule = PersonalRule(
            id=f"rule:{stable_id(decision.id)}",
            condition=condition,
            choice=decision.choice,
            scope=decision.scope,
            risk=decision.risk,
            confidence=decision.confidence,
            source_timestamp=decision.timestamp,
            evidence=decision.evidence,
        )
        store.upsert_rule(rule)
        created += 1
    return {"created": created, "skipped": skipped}


def match_rules(store: Store, request: DecisionRequest, limit: int = 5) -> list[RuleMatch]:
    query = "\n".join(filter(None, [request.question, request.project_context, *request.constraints]))
    matches: list[RuleMatch] = []
    for rule in store.rules():
        if request.before and rule.source_timestamp and rule.source_timestamp >= request.before:
            continue
        score = similarity(query, rule.condition)
        if score <= 0:
            continue
        matches.append(RuleMatch(
            rule_id=rule.id,
            score=score,
            condition=rule.condition,
            choice=rule.choice,
            evidence=rule.evidence,
        ))
    return sorted(matches, key=lambda item: (-item.score, item.rule_id))[:limit]


def export_rules(store: Store, path: Path) -> int:
    rules = store.rules(active_only=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for rule in rules:
            handle.write(json.dumps(rule.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return len(rules)
