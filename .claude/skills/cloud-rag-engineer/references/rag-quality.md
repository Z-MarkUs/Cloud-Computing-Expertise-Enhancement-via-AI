# RAG quality gates

Use the gates that match the change. Prefer deterministic checks that can run in demo mode; label model- or cloud-assisted judging separately.

## Retrieval

- Include answerable, paraphrased, ambiguous, adversarial, and intentionally unanswerable cases.
- Measure whether a relevant passage appears in the returned set, not merely whether any result exists. Record the corpus version and retrieval depth.
- Keep ranking inputs and thresholds observable enough to diagnose misses without logging sensitive document contents.
- Verify filters and source normalization cannot attach metadata from a different passage.

## Generation and citations

- Assert that every emitted citation resolves to a source returned for that request and that cited excerpts support the nearby claim.
- Reject fabricated, orphaned, duplicate, or path-traversal-style source identifiers.
- Require a clear insufficient-evidence response when the retrieved context cannot support an answer.
- Put trusted behavioral instructions outside retrieved content and delimit documents as data. Include a prompt-injection document in regression cases.
- Avoid tests that pass because they only search for a preferred phrase. Check observable answer/source relationships and API invariants.

## Evaluation

For a behavior-changing comparison, report the same fixed cases before and after. Track at least:

- answerable-case success;
- abstention correctness on unanswerable cases;
- citation validity and citation coverage;
- retrieval hit rate at the configured depth;
- latency distribution for the measured mode.

Keep qualitative judges optional and identify the judge, rubric, and nondeterminism. Never present demo-mode or synthetic results as live Azure performance.

## Provider and production boundary

- Normalize provider responses before orchestration and test missing fields, throttling, authentication failure, timeout, and malformed responses.
- Prefer workload identity or managed identity for deployed Azure resources. Keep local secrets in ignored environment files only.
- Apply explicit timeouts and bounded retries with jitter to transient idempotent operations; do not retry validation or authentication failures blindly.
- Correlate requests with safe identifiers and aggregate metrics. Do not log credentials, full prompts, retrieved document bodies, or hidden model reasoning.
