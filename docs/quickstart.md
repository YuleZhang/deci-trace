# Quickstart and staged acceptance

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp config.example.toml config.toml
```

All global options precede the subcommand. Use an isolated data directory while
sampling real histories.

## 1. Import real history

```bash
decitrace --config config.toml import --batch-id first-sample --max-files 20
decitrace --config config.toml quality-report --batch-id first-sample \
  --output artifacts/quality-sample.json
```

Acceptance: source files retain their hashes and mtimes; a second identical
import reports `unchanged`; malformed lines are counted, not fatal; every
normalized object has a source hash and line range.

## 2. Normalize and extract

```bash
decitrace --config config.toml extract
decitrace --config config.toml review-export artifacts/decision-review.jsonl
```

Edit only normalized fields such as `review_status`, `choice`, `rationale`,
`scope`, and `risk`. Set `review_status` to `accepted`, `rejected`, or
`corrected`, then apply:

```bash
decitrace --config config.toml review-apply artifacts/decision-review.jsonl
```

Acceptance: assistant proposals remain `agent_judgment`; explicit user choices
remain `explicit_user`; unknown rationale/outcome stays null; sampled evidence
resolves to the original line.

## 3. Build the policy

```bash
decitrace --config config.toml policy-build \
  --output artifacts/personal-policy.jsonl
```

Only reviewed explicit user decisions become rules. `--include-pending` is a
visible prototyping escape hatch and should not be used for a trusted policy.

Acceptance: every rule has source evidence and timestamp; rejected or agent-only
suggestions are excluded.

## 4. Ask the Decision Proxy

```bash
decitrace --config config.toml decide \
  "Should this local tool add a service or keep SQLite?" \
  --option "keep SQLite" --option "add a service" \
  --constraint "local-first" --risk low --baseline case
```

Available baselines are `rule`, `case`, and `case_llm`. Remote inference is off
by default. To enable it, explicitly set `[llm].enabled=true`, use an HTTPS or
localhost endpoint, and provide the key through the configured environment
variable. Prompt redaction remains on by default.

Acceptance: output includes historical cases/rules and evidence; weak,
conflicting, medium-risk under-supported, and all high-risk requests abstain.

## 5. Replay benchmark

```bash
decitrace --config config.toml evaluate --test-fraction 0.3 \
  --output-json artifacts/replay.json \
  --output-md artifacts/replay.md
```

Acceptance: each test request has a strict `before` cutoff; zero cited cases are
at or after that cutoff; report includes agreement, coverage, wrong automatic
answers, abstention, risk buckets, citation validity, latency, and known/unknown
token use. Historical preference agreement is reported separately from observed
execution outcomes.

## Tests

```bash
.venv/bin/pytest
```

The test suite uses synthetic transcripts. The optional real-history smoke test
uses explicitly supplied local roots and prints aggregate counts only.
