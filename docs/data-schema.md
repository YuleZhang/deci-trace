# Data schema

The canonical schema version is `1.0` and is defined by Pydantic models in
`src/decitrace/core/models.py`.

- **Session**: source, native-derived ID, project, time range, format version,
  source path/hash, and import batch.
- **Message**: role, content, timestamp, context, and one or more evidence refs.
- **ToolCall**: name, inert arguments/result, explicit status/exit code when
  available, and evidence. DeciTrace never executes imported calls.
- **Usage**: model, token categories, and cost/currency. Missing source fields
  stay null.
- **Interaction**: instruction, proposal, confirmation, rejection, correction,
  retry, or interruption with actor and confidence.
- **Outcome**: only observable test/build signals; unknown is not converted to
  success.
- **DecisionEpisode**: `context / question / options / choice / rationale /
  constraints / outcome / evidence / scope / confidence`, plus risk,
  attribution, epistemic status, and review status.
- **PersonalRule**: a reviewed explicit choice with condition, scope, risk,
  confidence, source timestamp, and evidence.

`EvidenceRef` contains a source path, SHA-256, 1-based line interval, raw event
type, session ID, and optional message ID. The raw format remains authoritative.

Attribution and epistemic status are orthogonal. An assistant recommendation is
`agent_judgment` plus `inference`; it cannot become a personal preference merely
because the user continued the session. Explicit user wording is
`explicit_user` plus `statement`. A passed test is a separate
`verified_result`, not proof that the preference was globally optimal.
