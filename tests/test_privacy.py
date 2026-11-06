import pytest

from decitrace.core.config import LLMConfig
from decitrace.decision.providers import OpenAICompatibleProvider, ProviderUnavailable, _redact


def test_remote_llm_is_disabled_by_default():
    with pytest.raises(ProviderUnavailable, match="llm_disabled"):
        OpenAICompatibleProvider(LLMConfig())


def test_redaction_removes_common_sensitive_values():
    value = {
        "email": "person@example.com",
        "secret": "Bearer " + "test_redaction_" + "placeholder",
        "path": "/home/" + "example-user/private/project",
    }
    redacted = _redact(value)
    assert redacted["email"] == "<redacted-email>"
    assert redacted["secret"] == "<redacted-secret>"
    assert redacted["path"] == "~/private/project"
