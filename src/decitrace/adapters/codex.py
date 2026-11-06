"""Version-tolerant Codex rollout JSONL adapter."""

from __future__ import annotations

import json
import re
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
from decitrace.core.util import jsonable_text, parse_datetime, stable_id

_EXIT_PATTERNS = (
    re.compile(r"Process exited with code\s+(-?\d+)", re.I),
    re.compile(r'"exit_code"\s*:\s*(-?\d+)', re.I),
)


class CodexAdapter(HistoryAdapter):
    source = SourceTool.CODEX

    def parse(self, path: Path, batch_id: str, source_hash: str) -> NormalizedBundle:
        native_id = path.stem
        project: str | None = None
        version: str | None = None
        started = ended = None
        messages: list[Message] = []
        calls: list[ToolCall] = []
        usage: list[Usage] = []
        warnings: list[str] = []
        pending_calls: dict[str, ToolCall] = {}
        current_model: str | None = None

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
                payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                timestamp = parse_datetime(row.get("timestamp") or payload.get("timestamp"))
                if timestamp is not None:
                    started = timestamp if started is None or timestamp < started else started
                    ended = timestamp if ended is None or timestamp > ended else ended

                if event_type == "session_meta":
                    native_id = str(payload.get("id") or payload.get("session_id") or native_id)
                    project = _string_or_none(payload.get("cwd")) or project
                    version = _string_or_none(payload.get("cli_version")) or version
                    continue
                if event_type == "turn_context":
                    current_model = _string_or_none(payload.get("model")) or current_model
                    project = _string_or_none(payload.get("cwd")) or project
                    continue

                evidence = _evidence(path, source_hash, line_no, event_type, native_id)
                if event_type == "response_item":
                    item_type = payload.get("type")
                    if item_type in {"message", "agent_message"}:
                        content = _message_text(payload.get("content"))
                        if content:
                            role = _role(payload.get("role"))
                            message_id = f"codex:{native_id}:{payload.get('id') or stable_id(path, line_no)}"
                            evidence.message_id = message_id
                            messages.append(Message(
                                id=message_id,
                                session_id=f"codex:{native_id}",
                                timestamp=timestamp,
                                role=role,
                                content=content,
                                context={"raw_item_type": item_type},
                                evidence=[evidence],
                            ))
                    elif item_type in {"function_call", "custom_tool_call"}:
                        call_id = str(payload.get("call_id") or payload.get("id") or stable_id(path, line_no))
                        call = ToolCall(
                            id=f"codex:{native_id}:tool:{call_id}",
                            session_id=f"codex:{native_id}",
                            timestamp=timestamp,
                            name=str(payload.get("name") or payload.get("tool_name") or "unknown"),
                            arguments=_decode_json(payload.get("arguments", payload.get("input"))),
                            evidence=[evidence],
                        )
                        pending_calls[call_id] = call
                        calls.append(call)
                    elif item_type in {"function_call_output", "custom_tool_call_output"}:
                        call_id = str(payload.get("call_id") or "")
                        call = pending_calls.get(call_id)
                        if call is not None:
                            result = payload.get("output", payload.get("result"))
                            call.result = result
                            call.evidence.append(evidence)
                            call.exit_code, call.status = _tool_status(result)
                elif event_type == "token_usage_record":
                    token_data = _usage_payload(payload)
                    usage.append(Usage(
                        id=f"codex:{native_id}:usage:{line_no}",
                        session_id=f"codex:{native_id}",
                        timestamp=timestamp,
                        model=current_model,
                        input_tokens=_nonnegative_int(token_data.get("input_tokens")),
                        output_tokens=_nonnegative_int(token_data.get("output_tokens")),
                        cached_input_tokens=_nonnegative_int(token_data.get("cached_input_tokens")),
                        reasoning_tokens=_nonnegative_int(token_data.get("reasoning_output_tokens")),
                        evidence=[evidence],
                    ))

        session_id = f"codex:{native_id}"
        _rebind_session(messages, calls, usage, session_id)
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
            metadata={"format": "codex_rollout_jsonl"},
        )
        return NormalizedBundle(
            session=session,
            messages=messages,
            tool_calls=calls,
            usage=usage,
            warnings=warnings,
        )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in {"input_text", "output_text", "text"}:
            text = block.get("text") or block.get("content")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts)


def _role(value: Any) -> Role:
    try:
        return Role(str(value))
    except ValueError:
        return Role.UNKNOWN


def _decode_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _tool_status(result: Any) -> tuple[int | None, ToolStatus]:
    text = jsonable_text(result)
    for pattern in _EXIT_PATTERNS:
        if match := pattern.search(text):
            code = int(match.group(1))
            return code, ToolStatus.SUCCESS if code == 0 else ToolStatus.FAILURE
    return None, ToolStatus.UNKNOWN


def _usage_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("usage", "turn_token_usage", "thread_token_usage", "last_token_usage"):
        if isinstance(payload.get(key), dict):
            return payload[key]
    info = payload.get("info")
    if isinstance(info, dict):
        for key in ("last_token_usage", "total_token_usage"):
            if isinstance(info.get(key), dict):
                return info[key]
    return {}


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _evidence(path: Path, digest: str, line: int, kind: str, native_id: str) -> EvidenceRef:
    return EvidenceRef(
        source_path=str(path), source_hash=digest, line_start=line, line_end=line,
        raw_event_type=kind, session_id=native_id,
    )


def _rebind_session(items: list[Any], calls: list[ToolCall], usage: list[Usage], session_id: str) -> None:
    for item in [*items, *calls, *usage]:
        item.session_id = session_id
