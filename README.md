# DeciTrace

DeciTrace is a local-first, evidence-preserving system that imports Codex CLI,
Claude Code, and StepGo transcripts, extracts reviewable decision episodes,
and evaluates offline decision policies without executing transcript content.

## Safety defaults

- Source histories are opened read-only and never modified.
- Imported text is untrusted data, never an instruction stream.
- Network/LLM use is disabled unless an explicit provider is configured.
- Unknown fields, outcomes, usage, and costs remain unknown.
- Every normalized object carries line-level source evidence.

See [docs/quickstart.md](docs/quickstart.md) and
[docs/architecture.md](docs/architecture.md).

## MVP capabilities

- Version-tolerant adapters for Codex, Claude Code, and StepGo JSONL.
- Pydantic schemas with file-hash and line-level evidence references.
- Incremental SQLite/FTS import with canonical-path and content-hash deduplication.
- Conservative decision, correction, preference, and observable-outcome candidates.
- Editable JSONL review flow before a candidate can become trusted policy.
- Rule, case-retrieval, and retrieval-plus-LLM decision baselines.
- Risk-aware abstention and chronological replay without future-case leakage.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp config.example.toml config.toml

.venv/bin/decitrace --config config.toml import --max-files 20
.venv/bin/decitrace --config config.toml extract
.venv/bin/decitrace --config config.toml review-export artifacts/review.jsonl
```

Review the exported candidates locally before building policy or processing a
full history. Personal databases, JSONL exports, local configuration, agent
state, logs, and credential files are excluded by `.gitignore`.

## Documentation

- [Architecture](docs/architecture.md)
- [Data schema](docs/data-schema.md)
- [Quickstart and acceptance criteria](docs/quickstart.md)
- [Future agent integration](docs/integration.md)
- [Privacy-preserving MVP validation](docs/experiments/mvp-validation.md)

## Development

```bash
.venv/bin/pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE).
