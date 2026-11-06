"""Adapter contract and source discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from decitrace.core.models import NormalizedBundle, SourceTool


class HistoryAdapter(ABC):
    source: SourceTool

    @abstractmethod
    def parse(self, path: Path, batch_id: str, source_hash: str) -> NormalizedBundle:
        """Parse one source file without mutating or executing its contents."""


def discover_jsonl(roots: Iterable[Path]) -> list[Path]:
    """Return deterministic canonical transcript candidates from existing roots."""
    found: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() and root.suffix == ".jsonl" else root.rglob("*.jsonl")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            canonical = str(candidate.resolve(strict=False))
            found.setdefault(canonical, candidate)
    return [found[key] for key in sorted(found)]
