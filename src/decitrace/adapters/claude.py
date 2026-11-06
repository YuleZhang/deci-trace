"""Claude Code project transcript JSONL adapter."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from decitrace.adapters.base import HistoryAdapter
from decitrace.core.models import (
    EvidenceRef,
    Message,
    NormalizedBundle,
    Role,
    Session,
    SourceTool,
    ToolCall,
    ToolStatus,
    Usage,
)
from decitrace.core.util import parse_datetime, stable_id

_EXIT = re.compile(r"(?:exit(?:ed)?(?: with)?(?: code)?|return code)\D{0,8}(-?\d+)", re.I)


class ClaudeAdapter(HistoryAdapter):
    source = SourceTool.CLAUDE

    def parse(self, path: Path, batch_id: str, source_hash: str) -> NormalizedBundle:
        native_id = path.stem
        project: str | None = None
        version: str | None = None
        started = ended = None
        messages: list[Message] = []
        calls: list[ToolCall] = []
        usages: list[Usage] = []
        warnings: list[str] = []
        event_counts: Counter[str] = Counter()
        pending: dict[str, ToolCall] = {}
        seen_usage: set[str] = set()
        final_cost: tuple[int, Any, Any] | None = None

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, 1):
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError as exc:
                    warnings.append(f"line {line_no}: invalid_json:{exc.msg}")
                    continue
                event_type = str(row.get("type", "unknown"))
                event_counts[event_type] += 1
                native_id = str(row.get("sessionId") or row.get("session_id") or native_id)
                project = _text(row.get("cwd")) or project
                version = _text(row.get("version")) or version
                timestamp = parse_datetime(row.get("timestamp"))
                if timestamp is not None:
                    started = timestamp if started is None or timestamp < started else started
                    ended = timestamp if ended is None or timestamp > ended else ended
                evidence = _evidence(path, source_hash, line_no, event_type, native_id)

                if event_type in {"user", "assistant"}:
                    message = row.get("message") if isinstance(row.get("message"), dict) else {}
                    blocks = message.get("content")
                    if isinstance(blocks, str):
                        blocks = [{"type": "text", "text": blocks}]
                    if not isinstance(blocks, list):
                        blocks = []
                    text_parts: list[str] = []
                    for block in blocks:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type")
                        if block_type == "text" and isinstance(block.get("text"), str):
                            text_parts.append(block["text"])
                        elif block_type == "tool_use":
                            tool_id = str(block.get("id") or stable_id(path, line_no, len(calls)))
                            call = ToolCall(
                                id=f"claude:{native_id}:tool:{tool_id}",
                                session_id=f"claude:{native_id}",
                                message_id=_message_id(native_id, row, line_no),
                                timestamp=timestamp,
                                name=str(block.get("name") or "unknown"),
                                arguments=block.get("input"),
                                evidence=[evidence.model_copy(deep=True)],
                            )
                            pending[tool_id] = call
                            calls.append(call)
                        elif block_type == "tool_result":
                            tool_id = str(block.get("tool_use_id") or "")
                            if call := pending.get(tool_id):
                                call.result = block.get("content")
                                call.status = ToolStatus.FAILURE if block.get("is_error") is True else ToolStatus.SUCCESS
                                call.exit_code = _exit_code(call.result)
                                call.evidence.append(evidence.model_copy(deep=True))
                    content = "\n".join(part for part in text_parts if part)
                    if content:
                        msg_id = _message_id(native_id, row, line_no)
                        msg_evidence = evidence.model_copy(update={"message_id": msg_id})
                        messages.append(Message(
                            id=msg_id,
                            session_id=f"claude:{native_id}",
                            timestamp=timestamp,
                            role=Role.ASSISTANT if event_type == "assistant" else Role.USER,
                            content=content,
                            context={
                                "parent_uuid": row.get("parentUuid"),
                                "is_sidechain": bool(row.get("isSidechain", False)),
                            },
                            evidence=[msg_evidence],
                        ))
                    if event_type == "assistant":
                        api_message_id = str(message.get("id") or _message_id(native_id, row, line_no))
                        data = message.get("usage")
                        if isinstance(data, dict) and api_message_id not in seen_usage:
                            seen_usage.add(api_message_id)
                            usages.append(_usage(native_id, line_no, timestamp, message, data, evidence))
                elif event_type == "cost-state":
                    final_cost = (line_no, row.get("totalCostUSD"), evidence)

        session_id = f"claude:{native_id}"
        for item in [*messages, *calls, *usages]:
            item.session_id = session_id
        if final_cost and isinstance(final_cost[1], (int, float)) and final_cost[1] >= 0:
            line_no, cost, evidence = final_cost
            usages.append(Usage(
                id=f"claude:{native_id}:cost:{line_no}", session_id=session_id,
                cost=float(cost), currency="USD", evidence=[evidence],
            ))
        session = Session(
            id=session_id,
            source=self.source,
            project_path=project,
            started_at=started,
            ended_at=ended,
            source_path=str(path),
            source_hash=source_hash,
            import_batch=batch_id,
            source_version=version,
            metadata={"format": "claude_project_jsonl", "event_counts": dict(event_counts)},
        )
        return NormalizedBundle(
            session=session, messages=messages, tool_calls=calls, usage=usages, warnings=warnings,
        )


def _message_id(native_id: str, row: dict[str, Any], line_no: int) -> str:
    return f"claude:{native_id}:msg:{row.get('uuid') or stable_id(native_id, line_no)}:{line_no}"


def _usage(
    native_id: str,
    line_no: int,
    timestamp: Any,
    message: dict[str, Any],
    data: dict[str, Any],
    evidence: EvidenceRef,
) -> Usage:
    output_details = data.get("output_tokens_details")
    reasoning = output_details.get("thinking_tokens") if isinstance(output_details, dict) else None
    return Usage(
        id=f"claude:{native_id}:usage:{message.get('id') or line_no}",
        session_id=f"claude:{native_id}",
        timestamp=timestamp,
        model=_text(message.get("model")),
        input_tokens=_int(data.get("input_tokens")),
        output_tokens=_int(data.get("output_tokens")),
        cached_input_tokens=_int(data.get("cache_read_input_tokens")),
        reasoning_tokens=_int(reasoning),
        evidence=[evidence.model_copy(deep=True)],
    )


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _exit_code(value: Any) -> int | None:
    if isinstance(value, str):
        match = _EXIT.search(value)
        return int(match.group(1)) if match else None
    return None


def _evidence(path: Path, digest: str, line: int, kind: str, native_id: str) -> EvidenceRef:
    return EvidenceRef(
        source_path=str(path), source_hash=digest, line_start=line, line_end=line,
        raw_event_type=kind, session_id=native_id,
    )
