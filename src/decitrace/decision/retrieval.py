"""Historical decision case retrieval."""

from __future__ import annotations

from decitrace.core.models import DecisionAttribution
from decitrace.core.storage import Store
from decitrace.decision.models import CaseMatch, DecisionRequest
from decitrace.decision.similarity import similarity


def retrieve_cases(
    store: Store,
    request: DecisionRequest,
    *,
    limit: int = 5,
    include_pending: bool = False,
) -> list[CaseMatch]:
    query = "\n".join(filter(None, [
        request.question,
        request.project_context,
        *request.options,
        *request.constraints,
    ]))
    matches: list[CaseMatch] = []
    for decision in store.decisions():
        if decision.attribution != DecisionAttribution.EXPLICIT_USER or not decision.choice:
            continue
        if not include_pending and decision.review_status not in {"accepted", "corrected"}:
            continue
        if decision.review_status == "rejected":
            continue
        if request.before is not None:
            if decision.timestamp is None or decision.timestamp >= request.before:
                continue
        case_text = "\n".join(filter(None, [
            decision.question,
            decision.context,
            *decision.options,
            *decision.constraints,
        ]))
        score = similarity(query, case_text)
        if score <= 0:
            continue
        matches.append(CaseMatch(
            decision_id=decision.id,
            score=score,
            question=decision.question,
            choice=decision.choice,
            rationale=decision.rationale,
            risk=decision.risk,
            timestamp=decision.timestamp,
            evidence=decision.evidence,
        ))
    return sorted(matches, key=lambda item: (-item.score, item.decision_id))[:limit]
