# Idea keynote compression recovery

Idea reference selection requests JSON Schema output when the selected model's
capabilities declare support, or JSON object mode when available. Both Chat
Completions and Responses use the existing transport conversion. If an endpoint
explicitly rejects a format, the current request falls back to the next declared
format, then to a prompt with local validation.

Single-paper capsules require exactly `summary` and `insight`, both non-empty
strings. The remaining-paper synthesis requires a non-empty `summary` string.
Invalid JSON, missing fields, and incorrect types trigger a repair request for
that capsule only. `idea.agent.keynote_json_repair_attempts` defaults to 2:
one initial response and at most two format repairs. Transport failures use the
existing chat retry policy; exhausted requests retain the original keynote.

Each response is saved before parsing under
`<idea-attempt>/keynote_compression/`. Checkpoints preserve paper identifiers,
original keynotes, complete raw responses, validation errors, and the final
capsule. Successful capsules are saved immediately and reused when the same
model, prompt, and source keynotes are processed again in that attempt directory.
Repairing a later capsule does not repeat earlier successful compressions.

After failed repairs, the capsule uses the original keynote as its summary,
keeps an empty insight, and records `compression_status: fallback`, its issues,
and its checkpoint path. A failed group synthesis preserves every constituent
keynote and paper identifier. Reference selection reports a degraded status and
continues to subsequent Idea stages; the fallback does not invalidate Survey.
