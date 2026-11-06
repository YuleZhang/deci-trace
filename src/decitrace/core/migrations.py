"""SQLite schema for normalized evidence and replay artifacts."""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_meta (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO schema_meta(version) VALUES(1);

CREATE TABLE IF NOT EXISTS import_files (
  canonical_path TEXT PRIMARY KEY,
  observed_path TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  source TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  status TEXT NOT NULL,
  session_id TEXT,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_duplicates (
  path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  source TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY(path, batch_id)
);
CREATE TABLE IF NOT EXISTS import_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL,
  source TEXT,
  path TEXT NOT NULL,
  line INTEGER,
  category TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  project_path TEXT,
  started_at TEXT,
  ended_at TEXT,
  data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  timestamp TEXT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  timestamp TEXT,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_records (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  timestamp TEXT,
  data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  timestamp TEXT,
  kind TEXT NOT NULL,
  data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  kind TEXT NOT NULL,
  data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  timestamp TEXT,
  choice TEXT,
  attribution TEXT NOT NULL,
  risk TEXT NOT NULL,
  review_status TEXT NOT NULL,
  data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rules (
  id TEXT PRIMARY KEY,
  scope TEXT,
  condition_text TEXT NOT NULL,
  choice TEXT NOT NULL,
  risk TEXT NOT NULL,
  confidence REAL NOT NULL,
  evidence_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decision_id TEXT NOT NULL,
  verdict TEXT NOT NULL,
  note TEXT,
  corrected_choice TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session_time ON messages(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_tools_session_time ON tool_calls(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_decisions_time ON decisions(timestamp);
CREATE INDEX IF NOT EXISTS idx_import_batch ON import_files(batch_id);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(id UNINDEXED, session_id UNINDEXED, content);
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(id UNINDEXED, question, choice, rationale, constraints);
"""
