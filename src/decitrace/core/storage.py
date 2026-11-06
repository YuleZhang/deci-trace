"""Transactional SQLite persistence and evidence queries."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from decitrace.core.migrations import SCHEMA_SQL
from decitrace.core.models import (
    DecisionEpisode,
    Interaction,
    Message,
    NormalizedBundle,
    Outcome,
    PersonalRule,
    Session,
    ToolCall,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_SQL)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def unchanged(self, canonical_path: str, size: int, mtime_ns: int) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM import_files WHERE canonical_path=? AND size=? AND mtime_ns=? AND status='imported'",
            (canonical_path, size, mtime_ns),
        ).fetchone()
        return row is not None

    def hash_exists(self, content_hash: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM import_files WHERE content_hash=?", (content_hash,)
        ).fetchone() is not None

    def save_bundle(
        self,
        bundle: NormalizedBundle,
        observed_path: Path,
        canonical_path: str,
        size: int,
        mtime_ns: int,
    ) -> None:
        session = bundle.session
        with self.connection:
            old = self.connection.execute(
                "SELECT session_id FROM import_files WHERE canonical_path=?", (canonical_path,)
            ).fetchone()
            if old and old["session_id"]:
                self._delete_session(old["session_id"])
            self.connection.execute("DELETE FROM import_files WHERE canonical_path=?", (canonical_path,))
            # A session ID belongs to one transcript snapshot in the current dataset.
            self.connection.execute("DELETE FROM import_files WHERE session_id=?", (session.id,))
            self._delete_session(session.id)
            self.connection.execute(
                "INSERT INTO sessions(id,source,project_path,started_at,ended_at,data_json) VALUES(?,?,?,?,?,?)",
                (session.id, session.source.value, session.project_path, _iso(session.started_at),
                 _iso(session.ended_at), session.model_dump_json()),
            )
            self._insert_messages(bundle.messages)
            self._insert_tools(bundle.tool_calls)
            self.connection.executemany(
                "INSERT INTO usage_records(id,session_id,timestamp,data_json) VALUES(?,?,?,?)",
                [(item.id, item.session_id, _iso(item.timestamp), item.model_dump_json()) for item in bundle.usage],
            )
            self.connection.execute(
                "INSERT INTO import_files(canonical_path,observed_path,content_hash,size,mtime_ns,source,batch_id,status,session_id,warnings_json,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (canonical_path, str(observed_path), session.source_hash, size, mtime_ns,
                 session.source.value, session.import_batch, "imported", session.id,
                 json.dumps(bundle.warnings, ensure_ascii=False), _now()),
            )
            for warning in bundle.warnings:
                line = _warning_line(warning)
                self._record_error_no_commit(
                    session.import_batch, session.source.value, str(observed_path), line,
                    "parse_warning", warning,
                )

    def _delete_session(self, session_id: str) -> None:
        for row in self.connection.execute("SELECT id FROM messages WHERE session_id=?", (session_id,)):
            self.connection.execute("DELETE FROM messages_fts WHERE id=?", (row[0],))
        for row in self.connection.execute("SELECT id FROM decisions WHERE session_id=?", (session_id,)):
            self.connection.execute("DELETE FROM decisions_fts WHERE id=?", (row[0],))
        self.connection.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def _insert_messages(self, messages: Iterable[Message]) -> None:
        for item in messages:
            self.connection.execute(
                "INSERT INTO messages(id,session_id,timestamp,role,content,data_json) VALUES(?,?,?,?,?,?)",
                (item.id, item.session_id, _iso(item.timestamp), item.role.value,
                 item.content, item.model_dump_json()),
            )
            self.connection.execute(
                "INSERT INTO messages_fts(id,session_id,content) VALUES(?,?,?)",
                (item.id, item.session_id, item.content),
            )

    def _insert_tools(self, calls: Iterable[ToolCall]) -> None:
        self.connection.executemany(
            "INSERT INTO tool_calls(id,session_id,timestamp,name,status,data_json) VALUES(?,?,?,?,?,?)",
            [(item.id, item.session_id, _iso(item.timestamp), item.name, item.status.value,
              item.model_dump_json()) for item in calls],
        )

    def record_duplicate(self, path: str, content_hash: str, batch_id: str, source: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO import_duplicates(path,content_hash,batch_id,source,recorded_at) VALUES(?,?,?,?,?)",
                (path, content_hash, batch_id, source, _now()),
            )

    def record_error(
        self, batch_id: str, source: str | None, path: str,
        category: str, detail: str, line: int | None = None,
    ) -> None:
        with self.connection:
            self._record_error_no_commit(batch_id, source, path, line, category, detail)

    def _record_error_no_commit(
        self, batch_id: str, source: str | None, path: str, line: int | None,
        category: str, detail: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO import_errors(batch_id,source,path,line,category,detail,created_at) VALUES(?,?,?,?,?,?,?)",
            (batch_id, source, path, line, category, detail, _now()),
        )

    def sessions(self) -> list[Session]:
        rows = self.connection.execute("SELECT data_json FROM sessions ORDER BY started_at,id")
        return [Session.model_validate_json(row[0]) for row in rows]

    def messages(self, session_id: str | None = None) -> list[Message]:
        if session_id:
            rows = self.connection.execute(
                "SELECT data_json FROM messages WHERE session_id=? ORDER BY timestamp,rowid", (session_id,)
            )
        else:
            rows = self.connection.execute("SELECT data_json FROM messages ORDER BY timestamp,rowid")
        return [Message.model_validate_json(row[0]) for row in rows]

    def tool_calls(self, session_id: str | None = None) -> list[ToolCall]:
        if session_id:
            rows = self.connection.execute(
                "SELECT data_json FROM tool_calls WHERE session_id=? ORDER BY timestamp,rowid", (session_id,)
            )
        else:
            rows = self.connection.execute("SELECT data_json FROM tool_calls ORDER BY timestamp,rowid")
        return [ToolCall.model_validate_json(row[0]) for row in rows]

    def decisions(self, reviewed_only: bool = False) -> list[DecisionEpisode]:
        sql = "SELECT data_json FROM decisions"
        params: tuple[object, ...] = ()
        if reviewed_only:
            sql += " WHERE review_status='accepted'"
        sql += " ORDER BY timestamp,id"
        return [DecisionEpisode.model_validate_json(row[0]) for row in self.connection.execute(sql, params)]

    def replace_derived(
        self,
        session_id: str,
        interactions: Iterable[Interaction],
        outcomes: Iterable[Outcome],
        decisions: Iterable[DecisionEpisode],
    ) -> None:
        interactions = list(interactions)
        outcomes = list(outcomes)
        decisions = list(decisions)
        with self.connection:
            old_ids = [row[0] for row in self.connection.execute(
                "SELECT id FROM decisions WHERE session_id=?", (session_id,)
            )]
            for decision_id in old_ids:
                self.connection.execute("DELETE FROM decisions_fts WHERE id=?", (decision_id,))
            self.connection.execute("DELETE FROM interactions WHERE session_id=?", (session_id,))
            self.connection.execute("DELETE FROM outcomes WHERE session_id=?", (session_id,))
            self.connection.execute("DELETE FROM decisions WHERE session_id=?", (session_id,))
            self.connection.executemany(
                "INSERT INTO interactions(id,session_id,timestamp,kind,data_json) VALUES(?,?,?,?,?)",
                [(item.id, item.session_id, _iso(item.timestamp), item.kind.value,
                  item.model_dump_json()) for item in interactions],
            )
            self.connection.executemany(
                "INSERT INTO outcomes(id,session_id,status,kind,data_json) VALUES(?,?,?,?,?)",
                [(item.id, item.session_id, item.status.value, item.kind,
                  item.model_dump_json()) for item in outcomes],
            )
            for item in decisions:
                self._insert_decision(item)

    def upsert_decision(self, item: DecisionEpisode) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM decisions_fts WHERE id=?", (item.id,))
            self.connection.execute("DELETE FROM decisions WHERE id=?", (item.id,))
            self._insert_decision(item)

    def _insert_decision(self, item: DecisionEpisode) -> None:
        self.connection.execute(
            "INSERT INTO decisions(id,session_id,timestamp,choice,attribution,risk,review_status,data_json) VALUES(?,?,?,?,?,?,?,?)",
            (item.id, item.session_id, _iso(item.timestamp), item.choice,
             item.attribution.value, item.risk.value, item.review_status,
             item.model_dump_json()),
        )
        self.connection.execute(
            "INSERT INTO decisions_fts(id,question,choice,rationale,constraints) VALUES(?,?,?,?,?)",
            (item.id, item.question, item.choice or "", item.rationale or "",
             " ".join(item.constraints)),
        )

    def outcomes(self, session_id: str | None = None) -> list[Outcome]:
        sql = "SELECT data_json FROM outcomes"
        params: tuple[object, ...] = ()
        if session_id:
            sql += " WHERE session_id=?"
            params = (session_id,)
        return [Outcome.model_validate_json(row[0]) for row in self.connection.execute(sql, params)]

    def upsert_rule(self, rule: PersonalRule) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO rules(id,scope,condition_text,choice,risk,confidence,evidence_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (rule.id, rule.scope, rule.condition, rule.choice, rule.risk.value,
                 rule.confidence, rule.model_dump_json(), int(rule.active),
                 _iso(rule.source_timestamp) or _now()),
            )

    def rules(self, active_only: bool = True) -> list[PersonalRule]:
        sql = "SELECT evidence_json FROM rules"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY created_at,id"
        return [PersonalRule.model_validate_json(row[0]) for row in self.connection.execute(sql)]

    def clear_rules(self) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM rules")

    def record_feedback(
        self, decision_id: str, verdict: str, note: str | None = None,
        corrected_choice: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO feedback(decision_id,verdict,note,corrected_choice,created_at) VALUES(?,?,?,?,?)",
                (decision_id, verdict, note, corrected_choice, _now()),
            )

    def quality_report(self, batch_id: str | None = None) -> dict[str, object]:
        where = " WHERE batch_id=?" if batch_id else ""
        params: tuple[object, ...] = (batch_id,) if batch_id else ()
        files = self.connection.execute(
            f"SELECT source,COUNT(*) count,SUM(size) bytes FROM import_files{where} GROUP BY source", params
        ).fetchall()
        errors = self.connection.execute(
            f"SELECT category,COUNT(*) count FROM import_errors{where} GROUP BY category", params
        ).fetchall()
        counts = {}
        tables = ("sessions", "messages", "tool_calls", "usage_records", "decisions", "outcomes")
        for table in tables:
            if batch_id:
                key = "id" if table == "sessions" else "session_id"
                sql = f"SELECT COUNT(*) FROM {table} t JOIN import_files f ON f.session_id=t.{key} WHERE f.batch_id=?"
                counts[table] = self.connection.execute(sql, params).fetchone()[0]
            else:
                counts[table] = self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if batch_id:
            missing = {
                "session_project": self.connection.execute(
                    "SELECT COUNT(*) FROM sessions s JOIN import_files f ON f.session_id=s.id WHERE f.batch_id=? AND s.project_path IS NULL",
                    params,
                ).fetchone()[0],
                "message_timestamp": self.connection.execute(
                    "SELECT COUNT(*) FROM messages m JOIN import_files f ON f.session_id=m.session_id WHERE f.batch_id=? AND m.timestamp IS NULL",
                    params,
                ).fetchone()[0],
                "decision_choice": self.connection.execute(
                    "SELECT COUNT(*) FROM decisions d JOIN import_files f ON f.session_id=d.session_id WHERE f.batch_id=? AND d.choice IS NULL",
                    params,
                ).fetchone()[0],
            }
        else:
            missing = {
                "session_project": self.connection.execute(
                    "SELECT COUNT(*) FROM sessions WHERE project_path IS NULL"
                ).fetchone()[0],
                "message_timestamp": self.connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE timestamp IS NULL"
                ).fetchone()[0],
                "decision_choice": self.connection.execute(
                    "SELECT COUNT(*) FROM decisions WHERE choice IS NULL"
                ).fetchone()[0],
            }
        return {
            "batch_id": batch_id,
            "files": [dict(row) for row in files],
            "duplicates": self.connection.execute(
                "SELECT COUNT(*) FROM import_duplicates" + (" WHERE batch_id=?" if batch_id else ""),
                params,
            ).fetchone()[0],
            "counts": counts,
            "missing_fields": missing,
            "errors": [dict(row) for row in errors],
        }


def _warning_line(warning: str) -> int | None:
    if warning.startswith("line "):
        try:
            return int(warning.split(":", 1)[0].split()[1])
        except (IndexError, ValueError):
            pass
    return None
