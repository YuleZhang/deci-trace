"""Portable JSONL review and feedback round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from decitrace.core.models import DecisionEpisode
from decitrace.core.storage import Store


VALID_REVIEW_STATUS = {"pending", "accepted", "rejected", "corrected"}


def export_review(store: Store, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    decisions = store.decisions()
    with path.open("w", encoding="utf-8") as handle:
        for decision in decisions:
            handle.write(json.dumps(decision.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return len(decisions)


def apply_review(store: Store, path: Path) -> dict[str, object]:
    report: dict[str, object] = {"applied": 0, "errors": []}
    existing = {item.id: item for item in store.decisions()}
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                decision = DecisionEpisode.model_validate_json(raw)
                if decision.id not in existing:
                    raise ValueError("unknown decision id")
                if decision.review_status not in VALID_REVIEW_STATUS:
                    raise ValueError("invalid review_status")
                old = existing[decision.id]
                store.upsert_decision(decision)
                if decision.review_status != old.review_status or decision.choice != old.choice:
                    store.record_feedback(
                        decision.id,
                        decision.review_status,
                        corrected_choice=decision.choice if decision.choice != old.choice else None,
                    )
                report["applied"] = int(report["applied"]) + 1
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                # Avoid copying possibly sensitive transcript text into error reports.
                report["errors"].append({"line": line_no, "error": type(exc).__name__})
    return report
