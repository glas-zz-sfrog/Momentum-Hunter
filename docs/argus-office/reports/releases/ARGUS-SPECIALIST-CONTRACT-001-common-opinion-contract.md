# ARGUS-SPECIALIST-CONTRACT-001 - Common Specialist Opinion Contract

## Status

- Branch: `codex/ARGUS-SPECIALIST-CONTRACT-001-common-opinion-contract`
- Base: synchronized canonical `ea05615`
- Implementation commit: `802f2d1`
- Classification: `IMPLEMENTED_PENDING_INTEGRATION`
- Runtime/install/activation: none

## Implementation

- Added immutable evidence-reference, confidence, and specialist-opinion
  records with canonical JSON and two domain-separated SHA-256 identities.
- Bound opinions to existing opportunity, candidate, setup, TradePlan,
  research-policy, evidence, specialist-version, status, and authority fields.
- Added exact target-chain validation so an opinion cannot silently attach to
  another setup or TradePlan.
- Distinguished evaluated, abstained, and failed outcomes. Confidence semantics
  reject uncalibrated probability claims, while feature-family disclosure
  exposes correlated evidence without creating a universal score.
- Restricted v1 to `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`; no arbiter,
  provider, broker, runtime, persistence, scheduler, or UI path exists.

## Verification

- Python compileall: pass.
- Focused specialist contract tests: 50/50 pass.
- Candidate lifecycle, DATA-004, evidence-integrity, and SETUP-002 bounded
  regression: 142/142 pass.
- Full Python discovery: 2,063/2,063 pass in 267.771 seconds.
- Diff check, credential-pattern scan, forbidden-capability import scan, and
  existing-runtime import scan: pass.
- Closeout adds explicit policy-fingerprint drift/tamper proof and confirms
  that future specialist IDs do not require a schema redesign.
- Canonical checkout, installed service, manifest, and August 17 job identity
  were read-only and unchanged during implementation.

## Promotion Boundary

Research evidence does not earn runtime authority by accumulation. Any future
promotion requires a separately authorized task, a new prospective sample and
policy identity, explicit authority semantics, and fresh Hard Chew proof.
