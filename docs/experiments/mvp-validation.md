# MVP validation record

## Privacy-preserving local smoke test

The adapters were exercised against representative local Codex, Claude, and
StepGo transcripts in an isolated temporary database. Exact machine-specific
file counts, byte sizes, timestamps, project paths, transcript contents, and
extracted personal decisions are intentionally not included in this public
repository.

The smoke test verified that:

- representative files from every supported adapter imported successfully;
- a repeated import was idempotent and skipped unchanged files;
- source SHA-256, size, and mtime were unchanged after processing;
- malformed JSONL was reported without aborting the import batch;
- sampled evidence references resolved to matching source hashes and valid line
  numbers;
- no transcript data was sent to an external LLM.

These checks demonstrate parser and provenance mechanics. They are not a claim
of semantic extraction accuracy, and no personal replay score is published.

## Automated validation

- Synthetic tests cover legacy/current adapter shapes, malformed JSONL,
  tool-call pairing, explicit unknown usage, incremental import and content-hash
  deduplication, source immutability, outcome linking, review round-trip,
  conflict/high-risk abstention, all three baselines, temporal leakage, remote
  LLM opt-in, and redaction.
- Synthetic chronological replay checks that `rule`, `case`, and `case_llm`
  never cite future cases.
- The LLM baseline uses a fake provider in tests.

Run the current suite with:

```bash
.venv/bin/pytest
```

## Required private quality gate

Before a user runs full-history extraction or trusts automatic decisions:

1. Export a bounded local sample to `artifacts/decision-review.jsonl`.
2. Record accepted/rejected/corrected labels and rationales privately.
3. Set a minimum precision threshold for explicit-user attribution and evidence
   correctness.
4. Run the full import and personal replay benchmark only after that threshold
   is met.

Reviewed data is required by default. With no reviewed evidence, the Decision
Proxy safely abstains.
