# Architecture

## Format research

The design was checked against representative local transcript samples without
printing conversation text or modifying source histories. Exact machine-specific
file counts, storage volumes, dates, project names, and transcript contents are
not included in this repository.

| source | default transcript location | observed format families |
|---|---|---|
| Codex | `~/.codex/sessions`, `archived_sessions` | old/new `session_meta`; `response_item`, `event_msg`, `turn_context`, `token_usage_record` |
| Claude | `~/.claude/projects` | `user`, `assistant`, `tool_use`, `tool_result`, system and attachment records across multiple versions |
| StepGo | `~/.stepgo/sessions/host` | `session.start/end`, `tool.call`, `hook.trigger`, stream records, including malformed-line recovery |

`~/.stepcode/codex/sessions` may resolve to `~/.codex/sessions`, and
`~/.stepcode/claude/projects` may resolve to `~/.claude/projects`. Import
therefore uses canonical paths plus SHA-256 identity. Internal transcript
formats are not stable APIs, so adapters are tolerant readers and unknown
records are reported.

Prompt history indexes such as `~/.codex/history.jsonl` and
`~/.claude/history.jsonl`, and volatile runtime metadata such as
`~/.claude/sessions/*.json`, are deliberately not treated as authoritative
transcripts. They can be added later as reconciliation indexes, but importing
them now would duplicate messages from rollout/project transcripts. Credential
and configuration JSON is never discovered.

## Data flow

```text
read-only roots -> adapters -> normalized bundle -> SQLite + FTS
                                      |
                                      v
                           candidate extraction
                                      |
                           JSONL review / feedback
                                      |
             rules | case retrieval | retrieval+LLM interface
                                      |
                          temporal replay benchmark
```

No transcript field is evaluated as code or treated as a DeciTrace command.
Raw files stay in place. The database stores normalized text and line-level
references, not copied raw events.

## Modules

- `adapters/`: source discovery and version-tolerant parsers.
- `core/`: Pydantic schema, configuration, hashing, SQLite migrations/storage.
- `extraction/`: conservative candidate interactions, decisions, and outcomes.
- `decision/`: risk gate, explicit rule matcher, FTS case retrieval, optional
  provider interface.
- `evaluation/`: chronological train/test split and leakage-safe replay.
- `cli/`: import, extract, review export/apply, query, decide, and evaluate.

## Schema and evidence

Every `Session`, `Message`, `ToolCall`, `Usage`, `Interaction`, `Outcome`, and
`DecisionEpisode` is versioned. `EvidenceRef` records source path, file hash,
1-based line range, raw event type, session ID, and message ID. Missing values
are `null`; costs and outcomes are never estimated.

Decision attribution is one of `explicit_user`, `agent_judgment`, `user_tacit`,
or `system_inferred`. Epistemic status separately distinguishes fact,
statement, inference, verified result, and unknown. Candidates default to
`pending` review.

## Storage and incremental import

SQLite is the source of truth. `import_files` records canonical path, hash,
size, mtime, batch, adapter, and status. A repeated hash is skipped even through
a different symlink. Changed append-only files are currently re-parsed and
transactionally replace their prior normalized rows; this is deterministic and
safe, while a future checkpoint can optimize very large live files.

FTS5 indexes messages and decision fields. JSONL review exports are portable,
editable artifacts. Structured errors preserve file/line/category without
stopping an import batch.

## Privacy and trust boundary

- Defaults are offline and local; LLM configuration is disabled.
- Known transcript directories are enumerated; credential/config files are not.
- Any future remote provider must require `llm.enabled=true` and redact before
  send by default.
- Tool arguments/results are data only and are never executed.
- Reports aggregate counts and missing fields, not transcript content.

## Milestone acceptance

Week 1 is accepted when representative fixtures and real read-only samples can
be imported twice idempotently, evidence resolves to valid lines, malformed
records appear in a quality report, and review JSONL can round-trip.

Week 2 is accepted when three baselines run behind the same API, high-risk or
weak/conflicting evidence abstains, replay uses only cases older than each test
case, and reports separate preference agreement from observed outcome status.
