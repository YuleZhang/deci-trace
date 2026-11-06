from __future__ import annotations

import json
from pathlib import Path

from decitrace.adapters.claude import ClaudeAdapter
from decitrace.adapters.codex import CodexAdapter
from decitrace.adapters.stepgo import StepGoAdapter
from decitrace.core.models import Role, ToolStatus
from decitrace.core.util import sha256_file


def _jsonl(path: Path, rows: list[dict], malformed: bool = False) -> Path:
    text = "\n".join(json.dumps(row) for row in rows) + "\n"
    if malformed:
        text += "{not-json\n"
    path.write_text(text, encoding="utf-8")
    return path


def test_codex_adapter_parses_messages_tools_usage_and_evidence(tmp_path):
    path = _jsonl(tmp_path / "rollout.jsonl", [
        {"type": "session_meta", "timestamp": "2025-01-01T00:00:00Z", "payload": {
            "id": "c1", "cwd": "/project", "cli_version": "1.0"}},
        {"type": "turn_context", "timestamp": "2025-01-01T00:00:01Z", "payload": {"model": "m1"}},
        {"type": "response_item", "timestamp": "2025-01-01T00:00:02Z", "payload": {
            "type": "message", "id": "m1", "role": "user",
            "content": [{"type": "input_text", "text": "choose sqlite"}]}},
        {"type": "response_item", "timestamp": "2025-01-01T00:00:03Z", "payload": {
            "type": "function_call", "call_id": "t1", "name": "shell",
            "arguments": json.dumps({"command": "pytest"})}},
        {"type": "response_item", "timestamp": "2025-01-01T00:00:04Z", "payload": {
            "type": "function_call_output", "call_id": "t1",
            "output": "Process exited with code 0"}},
        {"type": "token_usage_record", "timestamp": "2025-01-01T00:00:05Z", "payload": {
            "usage": {"input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 3}}},
    ])
    bundle = CodexAdapter().parse(path, "b1", sha256_file(path))
    assert bundle.session.id == "codex:c1"
    assert bundle.messages[0].role == Role.USER
    assert bundle.tool_calls[0].status == ToolStatus.SUCCESS
    assert bundle.tool_calls[0].exit_code == 0
    assert bundle.usage[0].model == "m1"
    assert bundle.usage[0].cost is None
    assert bundle.messages[0].evidence[0].line_start == 3


def test_claude_adapter_pairs_tool_result_and_deduplicates_usage(tmp_path):
    usage = {"input_tokens": 12, "output_tokens": 4, "cache_read_input_tokens": 2}
    path = _jsonl(tmp_path / "claude.jsonl", [
        {"type": "user", "sessionId": "s1", "uuid": "u1", "cwd": "/p",
         "timestamp": "2025-01-01T00:00:00Z", "version": "2.1",
         "message": {"role": "user", "content": "please test"}},
        {"type": "assistant", "sessionId": "s1", "uuid": "a1", "timestamp": "2025-01-01T00:00:01Z",
         "message": {"id": "api1", "role": "assistant", "model": "claude",
                     "usage": usage, "content": [{"type": "text", "text": "I recommend tests"},
                                                   {"type": "tool_use", "id": "tool1", "name": "Bash",
                                                    "input": {"command": "pytest"}}]}},
        {"type": "assistant", "sessionId": "s1", "uuid": "a1", "timestamp": "2025-01-01T00:00:01Z",
         "message": {"id": "api1", "role": "assistant", "model": "claude",
                     "usage": usage, "content": [{"type": "thinking", "thinking": "hidden"}]}},
        {"type": "user", "sessionId": "s1", "uuid": "r1", "timestamp": "2025-01-01T00:00:02Z",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool1",
                                                       "content": "ok", "is_error": False}]}},
    ], malformed=True)
    bundle = ClaudeAdapter().parse(path, "b", sha256_file(path))
    assert len(bundle.messages) == 2
    assert len(bundle.tool_calls) == 1
    assert bundle.tool_calls[0].status == ToolStatus.SUCCESS
    assert len(bundle.usage) == 1
    assert bundle.warnings and "invalid_json" in bundle.warnings[0]


def test_stepgo_adapter_keeps_only_inert_tool_data(tmp_path):
    path = _jsonl(tmp_path / "host.jsonl", [
        {"type": "session.start", "sessionId": "h1", "ts": "2025-01-01T00:00:00Z"},
        {"type": "tool.call", "sessionId": "h1", "ts": "2025-01-01T00:00:01Z",
         "toolName": "read", "data": {"input": {"path": "x"}, "success": True}},
    ])
    bundle = StepGoAdapter().parse(path, "b", sha256_file(path))
    assert bundle.session.id == "stepgo:h1"
    assert bundle.messages == []
    assert bundle.tool_calls[0].arguments == {"path": "x"}
