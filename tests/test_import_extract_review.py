import hashlib
import json
from pathlib import Path

from decitrace.core.importer import Importer
from decitrace.core.models import SourceTool
from decitrace.core.storage import Store
from decitrace.extraction.heuristics import Extractor
from decitrace.extraction.review import apply_review, export_review


def _source(path: Path) -> None:
    rows = [
        {"type": "session_meta", "timestamp": "2025-01-01T00:00:00Z",
         "payload": {"id": "s1", "cwd": "/project"}},
        {"type": "response_item", "timestamp": "2025-01-01T00:00:01Z", "payload": {
            "type": "message", "id": "a1", "role": "assistant",
            "content": [{"type": "output_text", "text": "I recommend SQLite or a service."}]}},
        {"type": "response_item", "timestamp": "2025-01-01T00:00:02Z", "payload": {
            "type": "message", "id": "u1", "role": "user",
            "content": [{"type": "input_text", "text": "I choose SQLite because it is local."}]}},
        {"type": "response_item", "timestamp": "2025-01-01T00:00:03Z", "payload": {
            "type": "function_call", "call_id": "t1", "name": "shell",
            "arguments": json.dumps({"command": "pytest"})}},
        {"type": "response_item", "timestamp": "2025-01-01T00:00:04Z", "payload": {
            "type": "function_call_output", "call_id": "t1", "output": "Process exited with code 0"}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_import_is_idempotent_deduplicated_and_reviewable(tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    original = root / "a.jsonl"
    duplicate = root / "b.jsonl"
    _source(original)
    duplicate.write_bytes(original.read_bytes())
    digest_before = hashlib.sha256(original.read_bytes()).hexdigest()
    mtime_before = original.stat().st_mtime_ns

    with Store(tmp_path / "db.sqlite3") as store:
        importer = Importer(store)
        roots = {SourceTool.CODEX: [root]}
        first = importer.run(roots, batch_id="first")
        assert first["imported"] == 1
        assert first["duplicate_hash"] == 1
        second = importer.run(roots, batch_id="second")
        assert second["unchanged"] == 1
        assert second["duplicate_hash"] == 1
        assert len(store.sessions()) == 1
        assert store.messages()[0].evidence[0].source_path == str(original.resolve())

        extracted = Extractor(store).run()
        assert extracted["decisions"] >= 1
        explicit = [item for item in store.decisions() if item.attribution.value == "explicit_user"]
        assert len(explicit) == 1
        assert explicit[0].outcome.status.value == "passed"

        review = tmp_path / "review.jsonl"
        assert export_review(store, review) >= 1
        rows = [json.loads(line) for line in review.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            if row["id"] == explicit[0].id:
                row["review_status"] = "accepted"
        review.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        result = apply_review(store, review)
        assert result["errors"] == []
        accepted = {item.id: item for item in store.decisions()}[explicit[0].id]
        assert accepted.review_status == "accepted"
        assert store.quality_report()["duplicates"] >= 1

    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest_before
    assert original.stat().st_mtime_ns == mtime_before
