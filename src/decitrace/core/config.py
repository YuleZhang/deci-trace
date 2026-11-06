"""Configuration loading with conservative local-only defaults."""

from __future__ import annotations

import os
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.8-3.10
    import tomli as tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codex: list[Path] = Field(default_factory=lambda: [
        Path("~/.codex/sessions"),
        Path("~/.codex/archived_sessions"),
        Path("~/.stepcode/codex/sessions"),
    ])
    claude: list[Path] = Field(default_factory=lambda: [
        Path("~/.claude/projects"),
        Path("~/.stepcode/claude/projects"),
    ])
    stepgo: list[Path] = Field(default_factory=lambda: [Path("~/.stepgo/sessions/host")])


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    endpoint: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int = 60
    redact_before_send: bool = True


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_dir: Path = Path("~/.local/share/decitrace")
    sources: SourceConfig = Field(default_factory=SourceConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    def expanded(self) -> "AppConfig":
        data = self.model_dump()
        data["data_dir"] = _expand(self.data_dir)
        for key, paths in data["sources"].items():
            data["sources"][key] = [_expand(Path(path)) for path in paths]
        return AppConfig.model_validate(data)


def _expand(path: Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser().resolve(strict=False)


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        return AppConfig().expanded()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return AppConfig.model_validate(raw).expanded()
