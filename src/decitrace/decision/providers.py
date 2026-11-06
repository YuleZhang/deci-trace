"""Explicitly enabled, replaceable LLM inference boundary."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError

from decitrace.core.config import LLMConfig
from decitrace.decision.models import CaseMatch, DecisionRequest

_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_SECRET = re.compile(r"(?i)(?:bearer\s+|sk-|api[_-]?key\s*[:=]\s*)[A-Za-z0-9_./+=-]{8,}")
_HOME = re.compile(r"/home/[^/\s]+")


@dataclass
class ProviderResult:
    choice: str
    rationale: str
    confidence: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    def infer(self, request: DecisionRequest, cases: list[CaseMatch]) -> ProviderResult:
        ...


class ProviderUnavailable(RuntimeError):
    pass


class _LLMAnswer(BaseModel):
    recommended_choice: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class OpenAICompatibleProvider:
    def __init__(self, config: LLMConfig):
        self.config = config
        if not config.enabled:
            raise ProviderUnavailable("llm_disabled")
        if config.provider != "openai_compatible" or not config.endpoint or not config.model:
            raise ProviderUnavailable("llm_configuration_incomplete")
        parsed = urlparse(config.endpoint)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ProviderUnavailable("llm_endpoint_must_use_https_or_localhost")

    def infer(self, request: DecisionRequest, cases: list[CaseMatch]) -> ProviderResult:
        payload = _prompt_payload(request, cases)
        if self.config.redact_before_send:
            payload = _redact(payload)
        prompt = (
            "Use only the supplied historical evidence. Return JSON with keys "
            "recommended_choice, rationale, confidence. Do not invent preferences. "
            "If evidence conflicts, set confidence below 0.5.\n" +
            json.dumps(payload, ensure_ascii=False)
        )
        body = json.dumps({
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            key = os.environ.get(self.config.api_key_env)
            if not key:
                raise ProviderUnavailable("llm_api_key_env_missing")
            headers["Authorization"] = f"Bearer {key}"
        request_obj = urllib.request.Request(self.config.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request_obj, timeout=self.config.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = raw["choices"][0]["message"]["content"]
            answer = _LLMAnswer.model_validate_json(content)
            usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
            return ProviderResult(
                choice=answer.recommended_choice,
                rationale=answer.rationale,
                confidence=answer.confidence,
                input_tokens=_token(usage.get("prompt_tokens")),
                output_tokens=_token(usage.get("completion_tokens")),
            )
        except (OSError, KeyError, IndexError, ValueError, ValidationError) as exc:
            raise ProviderUnavailable(f"llm_request_failed:{type(exc).__name__}") from exc


def _prompt_payload(request: DecisionRequest, cases: list[CaseMatch]) -> dict[str, Any]:
    return {
        "current": request.model_dump(mode="json"),
        "historical_cases": [
            {
                "decision_id": case.decision_id,
                "score": case.score,
                "question": case.question,
                "choice": case.choice,
                "rationale": case.rationale,
            }
            for case in cases
        ],
    }


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        value = _EMAIL.sub("<redacted-email>", value)
        value = _SECRET.sub("<redacted-secret>", value)
        return _HOME.sub("~", value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _token(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None
