"""Versioned normalized schema; missing source facts remain ``None``."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class StrEnum(str, Enum):
    """Python 3.8-compatible string enum."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceTool(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    STEPGO = "stepgo"
    UNKNOWN = "unknown"


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    UNKNOWN = "unknown"


class EvidenceRef(StrictModel):
    source_path: str
    source_hash: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    raw_event_type: str | None = None
    session_id: str | None = None
    message_id: str | None = None


class Session(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    source: SourceTool
    project_path: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    source_path: str
    source_hash: str
    import_batch: str
    source_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Message(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    session_id: str
    timestamp: datetime | None = None
    role: Role
    content: str
    context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(min_length=1)


class ToolStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"
    INTERRUPTED = "interrupted"


class ToolCall(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    session_id: str
    message_id: str | None = None
    timestamp: datetime | None = None
    name: str
    arguments: Any = None
    result: Any = None
    status: ToolStatus = ToolStatus.UNKNOWN
    exit_code: int | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class Usage(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    session_id: str
    message_id: str | None = None
    timestamp: datetime | None = None
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0)
    currency: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class InteractionKind(StrEnum):
    INSTRUCTION = "instruction"
    PROPOSAL = "proposal"
    CONFIRMATION = "confirmation"
    REJECTION = "rejection"
    CORRECTION = "correction"
    RETRY = "retry"
    INTERRUPTION = "interruption"
    UNKNOWN = "unknown"


class Interaction(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    session_id: str
    kind: InteractionKind
    timestamp: datetime | None = None
    actor: Role
    content: str
    related_message_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class OutcomeStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Outcome(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    session_id: str
    status: OutcomeStatus
    kind: str
    summary: str | None = None
    observable: bool = False
    evidence: list[EvidenceRef] = Field(default_factory=list)


class DecisionAttribution(StrEnum):
    EXPLICIT_USER = "explicit_user"
    AGENT_JUDGMENT = "agent_judgment"
    USER_TACIT = "user_tacit"
    SYSTEM_INFERRED = "system_inferred"


class EpistemicStatus(StrEnum):
    FACT = "fact"
    STATEMENT = "statement"
    INFERENCE = "inference"
    VERIFIED_RESULT = "verified_result"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class DecisionEpisode(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    session_id: str
    timestamp: datetime | None = None
    context: str | None = None
    question: str
    options: list[str] = Field(default_factory=list)
    choice: str | None = None
    rationale: str | None = None
    constraints: list[str] = Field(default_factory=list)
    outcome: Outcome | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    scope: str | None = None
    confidence: float = Field(ge=0, le=1)
    attribution: DecisionAttribution
    epistemic_status: EpistemicStatus
    risk: RiskLevel = RiskLevel.UNKNOWN
    review_status: str = "pending"


class PersonalRule(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    condition: str
    choice: str
    scope: str | None = None
    risk: RiskLevel = RiskLevel.UNKNOWN
    confidence: float = Field(ge=0, le=1)
    source_timestamp: datetime | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    active: bool = True


class NormalizedBundle(StrictModel):
    session: Session
    messages: list[Message] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: list[Usage] = Field(default_factory=list)
    interactions: list[Interaction] = Field(default_factory=list)
    outcomes: list[Outcome] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
