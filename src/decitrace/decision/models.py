"""Decision proxy request/response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from decitrace.core.models import EvidenceRef, RiskLevel


class ProxyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionRequest(ProxyModel):
    question: str = Field(min_length=1)
    project_context: str | None = None
    options: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.UNKNOWN
    before: datetime | None = None


class CaseMatch(ProxyModel):
    decision_id: str
    score: float = Field(ge=0, le=1)
    question: str
    choice: str | None
    rationale: str | None = None
    risk: RiskLevel
    timestamp: datetime | None = None
    evidence: list[EvidenceRef]


class RuleMatch(ProxyModel):
    rule_id: str
    score: float = Field(ge=0, le=1)
    condition: str
    choice: str
    evidence: list[EvidenceRef]


class Recommendation(ProxyModel):
    baseline: str
    action: str
    recommended_choice: str | None = None
    rationale: str
    cases: list[CaseMatch] = Field(default_factory=list)
    rules: list[RuleMatch] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    evidence_sufficiency: str
    risk: RiskLevel
    abstain_reason: str | None = None
    latency_ms: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
