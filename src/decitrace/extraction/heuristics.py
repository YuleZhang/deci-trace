"""Conservative heuristic extraction; candidates always require review."""

from __future__ import annotations

import re
from typing import Any

from decitrace.core.models import (
    DecisionAttribution,
    DecisionEpisode,
    EpistemicStatus,
    Interaction,
    InteractionKind,
    Message,
    Outcome,
    OutcomeStatus,
    RiskLevel,
    Role,
    ToolCall,
    ToolStatus,
)
from decitrace.core.storage import Store
from decitrace.core.util import jsonable_text, stable_id

_CONFIRM = re.compile(r"(?:^|\b)(?:同意|确认|可以|就这样|按这个|yes|agree|approved?)(?:\b|[，。！])", re.I)
_REJECT = re.compile(r"(?:不要|否决|拒绝|不行|不同意|reject|do not|don't)", re.I)
_CORRECT = re.compile(r"(?:改成|应该是|不是.+而是|你错了|纠正|actually|instead|that's wrong|should be)", re.I)
_RETRY = re.compile(r"(?:重试|再试|重新来|retry|try again)", re.I)
_INTERRUPT = re.compile(r"(?:停止|先别|取消|中断|stop|cancel|abort)", re.I)
_PROPOSAL = re.compile(r"(?:建议|推荐|方案|可以选择|recommend|suggest|option|should use)", re.I)
_EXPLICIT_DECISION = re.compile(
    r"(?:我(?:选择|决定|倾向|更喜欢)|就用|采用|改用|优先|必须|保持|不要.+(?:用|引入)|"
    r"I\s+(?:choose|decide|prefer)|use\s+.+\s+instead|must\s+(?:use|keep|avoid))",
    re.I,
)
_RATIONALE = re.compile(r"(?:因为|原因是|考虑到|为了|because|since|in order to)\s*([^。.!?\n]+)", re.I)
_HIGH_RISK = re.compile(r"(?:生产|线上|deploy|delete|删除|凭证|credential|密钥|secret|迁移数据库|migration|支付|security)", re.I)
_MEDIUM_RISK = re.compile(r"(?:架构|依赖|dependency|API|性能|performance|数据库|schema|兼容|breaking)", re.I)
_OUTCOME_COMMAND = re.compile(r"(?:pytest|unittest|ctest|cargo test|npm test|pnpm test|build|cmake|ninja|make\b|mvn test|gradle)", re.I)


class Extractor:
    def __init__(self, store: Store):
        self.store = store

    def run(self) -> dict[str, int]:
        totals = {"sessions": 0, "interactions": 0, "outcomes": 0, "decisions": 0}
        for session in self.store.sessions():
            interactions, outcomes, decisions = self.extract_session(
                session.id,
                self.store.messages(session.id),
                self.store.tool_calls(session.id),
            )
            self.store.replace_derived(session.id, interactions, outcomes, decisions)
            totals["sessions"] += 1
            totals["interactions"] += len(interactions)
            totals["outcomes"] += len(outcomes)
            totals["decisions"] += len(decisions)
        return totals

    def extract_session(
        self, session_id: str, messages: list[Message], calls: list[ToolCall]
    ) -> tuple[list[Interaction], list[Outcome], list[DecisionEpisode]]:
        interactions = self._interactions(session_id, messages)
        outcomes = self._outcomes(session_id, calls)
        decisions: list[DecisionEpisode] = []
        previous: Message | None = None
        for message in messages:
            if message.role == Role.USER and _EXPLICIT_DECISION.search(message.content):
                decisions.append(self._user_decision(session_id, message, previous, outcomes))
            elif message.role == Role.ASSISTANT and _PROPOSAL.search(message.content):
                # Kept as agent judgment, never promoted to a user preference.
                decisions.append(self._agent_judgment(session_id, message, outcomes))
            if message.role in {Role.USER, Role.ASSISTANT}:
                previous = message
        return interactions, outcomes, decisions

    def _interactions(self, session_id: str, messages: list[Message]) -> list[Interaction]:
        result: list[Interaction] = []
        for message in messages:
            kind: InteractionKind | None = None
            confidence = 0.9
            if message.role == Role.USER:
                if _CORRECT.search(message.content):
                    kind = InteractionKind.CORRECTION
                elif _REJECT.search(message.content):
                    kind = InteractionKind.REJECTION
                elif _CONFIRM.search(message.content):
                    kind = InteractionKind.CONFIRMATION
                elif _RETRY.search(message.content):
                    kind = InteractionKind.RETRY
                elif _INTERRUPT.search(message.content):
                    kind = InteractionKind.INTERRUPTION
                else:
                    kind = InteractionKind.INSTRUCTION
                    confidence = 0.98
            elif message.role == Role.ASSISTANT and _PROPOSAL.search(message.content):
                kind = InteractionKind.PROPOSAL
                confidence = 0.65
            if kind is not None:
                result.append(Interaction(
                    id=f"interaction:{stable_id(message.id, kind.value)}",
                    session_id=session_id,
                    kind=kind,
                    timestamp=message.timestamp,
                    actor=message.role,
                    content=message.content,
                    related_message_ids=[message.id],
                    evidence=message.evidence,
                    confidence=confidence,
                ))
        return result

    def _outcomes(self, session_id: str, calls: list[ToolCall]) -> list[Outcome]:
        outcomes: list[Outcome] = []
        for call in calls:
            command = _command(call.arguments)
            if not _OUTCOME_COMMAND.search(command) or call.status == ToolStatus.UNKNOWN:
                continue
            status = OutcomeStatus.PASSED if call.status == ToolStatus.SUCCESS else OutcomeStatus.FAILED
            outcomes.append(Outcome(
                id=f"outcome:{stable_id(call.id)}",
                session_id=session_id,
                status=status,
                kind="test_or_build",
                summary=f"{call.name} reported {status.value}",
                observable=True,
                evidence=call.evidence,
            ))
        return outcomes

    def _user_decision(
        self, session_id: str, message: Message, previous: Message | None,
        outcomes: list[Outcome],
    ) -> DecisionEpisode:
        question = _clip(previous.content, 1200) if previous else "Historical user decision"
        evidence = ([*previous.evidence, *message.evidence] if previous else message.evidence)
        return DecisionEpisode(
            id=f"decision:{stable_id(message.id, 'explicit_user')}",
            session_id=session_id,
            timestamp=message.timestamp,
            context=_clip(previous.content, 2000) if previous else None,
            question=question,
            options=_options(previous.content) if previous else [],
            choice=_clip(message.content, 2000),
            rationale=_rationale(message.content),
            constraints=_constraints(message.content),
            outcome=_next_outcome(message, outcomes),
            evidence=evidence,
            scope=None,
            confidence=0.82,
            attribution=DecisionAttribution.EXPLICIT_USER,
            epistemic_status=EpistemicStatus.STATEMENT,
            risk=_risk(message.content),
        )

    def _agent_judgment(
        self, session_id: str, message: Message, outcomes: list[Outcome]
    ) -> DecisionEpisode:
        return DecisionEpisode(
            id=f"decision:{stable_id(message.id, 'agent_judgment')}",
            session_id=session_id,
            timestamp=message.timestamp,
            context=None,
            question="Agent-proposed technical choice",
            options=_options(message.content),
            choice=_clip(message.content, 2000),
            constraints=_constraints(message.content),
            outcome=_next_outcome(message, outcomes),
            evidence=message.evidence,
            confidence=0.45,
            attribution=DecisionAttribution.AGENT_JUDGMENT,
            epistemic_status=EpistemicStatus.INFERENCE,
            risk=_risk(message.content),
        )


def _command(arguments: Any) -> str:
    if isinstance(arguments, dict):
        for key in ("command", "cmd", "script"):
            if key in arguments:
                return jsonable_text(arguments[key])
    return jsonable_text(arguments)


def _options(text: str) -> list[str]:
    options = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^(?:[-*]|\d+[.)]|方案\s*[A-Z一二三四五])\s*", stripped, re.I):
            options.append(re.sub(r"^(?:[-*]|\d+[.)])\s*", "", stripped))
    return options[:8]


def _rationale(text: str) -> str | None:
    match = _RATIONALE.search(text)
    return _clip(match.group(1).strip(), 1000) if match else None


def _constraints(text: str) -> list[str]:
    markers = re.compile(r"(?:必须|不得|不要|只允许|本地|离线|must|avoid|only|without)", re.I)
    return [_clip(part.strip(), 500) for part in re.split(r"[。.!?\n]", text) if markers.search(part)][:8]


def _risk(text: str) -> RiskLevel:
    if _HIGH_RISK.search(text):
        return RiskLevel.HIGH
    if _MEDIUM_RISK.search(text):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _next_outcome(message: Message, outcomes: list[Outcome]) -> Outcome | None:
    # Outcomes lack a standalone timestamp in v1; evidence line order is used only
    # when source path matches, avoiding cross-file/session inference.
    source = message.evidence[-1]
    candidates = [outcome for outcome in outcomes if outcome.evidence and
                  outcome.evidence[0].source_path == source.source_path and
                  outcome.evidence[0].line_start > source.line_end]
    return min(candidates, key=lambda item: item.evidence[0].line_start) if candidates else None


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
