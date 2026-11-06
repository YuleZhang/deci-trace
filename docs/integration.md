# Future agent integration

DeciTrace exposes a stable local CLI boundary before any direct Codex/Claude
integration is attempted.

1. An agent serializes `DecisionRequest` fields: question, project context,
   candidates, constraints, risk, and optional historical cutoff.
2. It invokes `decitrace decide` or a future in-process API.
3. It consumes `Recommendation` only when `action=answer`; otherwise it asks the
   user. Evidence references are shown with the recommendation.
4. Production adapters must preserve the host agent's own approval mechanism.
   DeciTrace does not approve tool calls, edit code, or bypass confirmations.
5. The eventual feedback hook records the user's correction as a new reviewed
   episode/version; it never rewrites original evidence.

The Python provider protocol in `decision/providers.py` is replaceable. Remote
providers are opt-in; a local model provider can implement the same interface
without changing decision or evaluation code.
