"""Incremental, read-only transcript import orchestration."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable

from decitrace.adapters.base import HistoryAdapter, discover_jsonl
from decitrace.adapters.claude import ClaudeAdapter
from decitrace.adapters.codex import CodexAdapter
from decitrace.adapters.stepgo import StepGoAdapter
from decitrace.core.models import SourceTool
from decitrace.core.storage import Store
from decitrace.core.util import sha256_file

ADAPTERS: dict[SourceTool, HistoryAdapter] = {
    SourceTool.CODEX: CodexAdapter(),
    SourceTool.CLAUDE: ClaudeAdapter(),
    SourceTool.STEPGO: StepGoAdapter(),
}


class Importer:
    def __init__(self, store: Store):
        self.store = store

    def run(
        self,
        roots: dict[SourceTool, Iterable[Path]],
        *,
        batch_id: str | None = None,
        max_files: int | None = None,
    ) -> dict[str, object]:
        batch_id = batch_id or f"batch-{uuid.uuid4()}"
        report: dict[str, object] = {
            "batch_id": batch_id,
            "discovered": 0,
            "imported": 0,
            "unchanged": 0,
            "duplicate_hash": 0,
            "deferred_changed": 0,
            "failed": 0,
        }
        candidates: list[tuple[SourceTool, Path]] = []
        seen: set[str] = set()
        for source, source_roots in roots.items():
            for path in discover_jsonl(source_roots):
                canonical = str(path.resolve(strict=False))
                if canonical in seen:
                    continue
                seen.add(canonical)
                candidates.append((source, path))
        candidates.sort(key=lambda item: str(item[1]))
        if max_files is not None:
            candidates = candidates[:max_files]
        report["discovered"] = len(candidates)

        for source, path in candidates:
            canonical = str(path.resolve(strict=False))
            try:
                stat = path.stat()
                if self.store.unchanged(canonical, stat.st_size, stat.st_mtime_ns):
                    report["unchanged"] = int(report["unchanged"]) + 1
                    continue
                digest = sha256_file(path)
                if self.store.hash_exists(digest):
                    self.store.record_duplicate(str(path), digest, batch_id, source.value)
                    report["duplicate_hash"] = int(report["duplicate_hash"]) + 1
                    continue
                source_path = Path(canonical)
                bundle = ADAPTERS[source].parse(source_path, batch_id, digest)
                after = path.stat()
                if after.st_size != stat.st_size or after.st_mtime_ns != stat.st_mtime_ns:
                    report["deferred_changed"] = int(report["deferred_changed"]) + 1
                    self.store.record_error(
                        batch_id, source.value, str(path), "source_changed_during_import",
                        "file changed while being read; deferred to next incremental run",
                    )
                    continue
                self.store.save_bundle(
                    bundle, path, canonical, stat.st_size, stat.st_mtime_ns,
                )
                report["imported"] = int(report["imported"]) + 1
            except (OSError, ValueError, TypeError) as exc:
                report["failed"] = int(report["failed"]) + 1
                self.store.record_error(
                    batch_id, source.value, str(path), "import_failure",
                    f"adapter raised {type(exc).__name__}",
                )
        return report
