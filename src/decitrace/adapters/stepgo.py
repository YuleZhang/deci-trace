"""StepGo host telemetry adapter (metadata/tool events, not full chat text)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from decitrace.adapters.base import HistoryAdapter
from decitrace.core.models import EvidenceRef, NormalizedBundle, Session, SourceTool, ToolCall, ToolStatus
from decitrace.core.util import parse_datetime, stable_id


class StepGoAdapter(HistoryAdapter):
    source = SourceTool.STEPGO

    def parse(self, path: Path, batch_id: str, source_hash: str) -> NormalizedBundle:
        native_id = path.stem
        project: str | None = None
        agent: str | None = None
        started = ended = None
        calls: list[ToolCall] = []
        warnings: list[str] = []
        counts: Counter[str] = Counter()

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, 1):
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError as exc:
                    warnings.append(f"line {line_no}: invalid_json:{exc.msg}")
                    continue
                kind = str(row.get("type", "unknown"))
                counts[kind] += 1
                native_id = str(row.get("sessionId") or native_id)
                project = row.get("cwd") if isinstance(row.get("cwd"), str) else project
                agent = row.get("agent") if isinstance(row.get("agent"), str) else agent
                timestamp = parse_datetime(row.get("ts"))
                if timestamp is not None:
                    started = timestamp if started is None or timestamp < started else started
                    ended = timestamp if ended is None or timestamp > ended else ended
                if kind != "tool.call":
                    continue
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                status = _status(data)
                evidence = EvidenceRef(
                    source_path=str(path), source_hash=source_hash,
                    line_start=line_no, line_end=line_no, raw_event_type=kind,
                    session_id=native_id,
                )
                calls.append(ToolCall(
                    id=f"stepgo:{native_id}:tool:{stable_id(path, line_no)}",
                    session_id=f"stepgo:{native_id}",
                    timestamp=timestamp,
                    name=str(row.get("toolName") or data.get("tool") or "unknown"),
                    arguments=data.get("arguments", data.get("input")),
                    result=data.get("result", data.get("output")),
                    status=status,
                    exit_code=data.get("exit_code") if isinstance(data.get("exit_code"), int) else None,
                    evidence=[evidence],
                ))

        session_id = f"stepgo:{native_id}"
        for call in calls:
            call.session_id = session_id
        session = Session(
            id=session_id,
            source=self.source,
            project_path=project,
            started_at=started,
            ended_at=ended,
            source_path=str(path),
            source_hash=source_hash,
            import_batch=batch_id,
            metadata={"format": "stepgo_host_jsonl", "agent": agent, "event_counts": dict(counts)},
        )
        return NormalizedBundle(session=session, tool_calls=calls, warnings=warnings)


def _status(data: dict[str, Any]) -> ToolStatus:
    if data.get("is_error") is True or data.get("success") is False:
        return ToolStatus.FAILURE
    if data.get("success") is True:
        return ToolStatus.SUCCESS
    code = data.get("exit_code")
    if isinstance(code, int):
        return ToolStatus.SUCCESS if code == 0 else ToolStatus.FAILURE
    return ToolStatus.UNKNOWN
