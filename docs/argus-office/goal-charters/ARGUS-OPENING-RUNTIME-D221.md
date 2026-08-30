# ARGUS-OPENING-RUNTIME-D221 Goal Charter

## Goal

Build an isolated opening-runtime successor from canonical `23ee162373654e1db91af4c19f75bbc7887e3174`, prove its authoritative dependency closure and environment identity, and exercise the actual opening orchestration with preserved Aug. 14 Finviz and Schwab evidence.

## Boundaries

- D220 remains the installed rollback release.
- No production release, channel, service, scheduler, manifest, or canonical Git mutation.
- Only external provider and clock boundaries may consume preserved evidence.
- No account, position, Paper, Shadow, broker, or order capability.
- The replay is labeled `OFFLINE_PRESERVED_OPENING_REPLAY` and never becomes prospective evidence.

## Acceptance

- The D221 candidate is built from the exact clean canonical base using the authoritative V2.1 closure.
- The isolated runtime gate matches if the candidate is selected in the isolated release store.
- The actual `tools.capture_job.main` chain produces immutable capture, integrity, score-breakdown, readiness, and TradePlan artifacts.
- Preserved Finviz and Schwab evidence remains unchanged and no network call occurs.
- D220's entire release tree remains byte-for-byte unchanged.
- Focused, relevant, full-suite, compile, secret, capability, and protected-path checks pass.
- A sanitized, manifest-verified, self-contained second-eye ZIP is produced without promoting or merging D221.
