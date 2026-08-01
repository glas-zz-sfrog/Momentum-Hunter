# ARGUS-SHADOW-024 - Offline Terminal Review Evidence Packet

## Status

- Branch: `codex/ARGUS-SHADOW-024-offline-terminal-review-packet`
- Base: canonical frozen `ddc09f8`
- Classification: `IMPLEMENTED_PENDING_INTEGRATION_AFTER_MONDAY_EVIDENCE`
- Merge: prohibited until Monday's operational evidence is preserved
- Canonical runtime impact: none

## Implementation

`momentum_hunter/terminal_review_packet.py` provides a pure offline builder API and a
standalone CLI:

```text
python -m momentum_hunter.terminal_review_packet \
  --event-id <ID> --output-dir <PATH> \
  --state-path <PATH> --decision-cycles-path <PATH> \
  --handoff-path <PATH> --report-path <PATH> \
  --activation-path <PATH> --selection-policy-path <PATH>
```

The command reads only explicit files and emits `terminal-review-<EVENT_ID>.json` and
`.md`. It has no default production path and no scheduler, service, host, provider,
broker, WPF, or Codex integration.

## Supported Terminal Evidence

- Completed winner, loser, and flat FakeBroker trades.
- Terminal unfilled/rejected and cancelled entry orders.
- Invalidated/ambiguous exit evidence without invented outcome values.
- Legitimate no-eligible-candidate cycles, including risk and stale-quote blocks.

## Packet Contract

- Schema version, stable packet ID, SHA-256 packet fingerprint, terminal timestamp,
  source-event identity, and exact input hashes.
- Ten sections covering event identity; capture/candidate evidence; TradePlan; Risk
  Governor; selection; lifecycle; performance; counterfactuals; data/system quality;
  and deterministic review questions.
- Every review field is a stored fact, deterministic derivation, missing value, or
  review question.
- Counterfactual rows always say `COUNTERFACTUAL — NOT AN OFFICIAL TRADE`; Markdown
  renders the persisted packet and never supplies interpretation.

## Integrity And Security

- Current activation and selection policy use their canonical validators.
- Event, report, handoff, policy, sample, fill-model, arm, opportunity, and selection
  identities must agree.
- Terminal trades pass the existing Shadow audit and lifecycle validators.
- Input hashes are checked before and after output creation.
- Exact duplicates return the same packet identity and bytes.
- Existing conflicts fail closed without overwrite.
- New partial outputs and outputs raced by a source change are removed; pre-existing
  artifacts are never deleted.
- Secret-key names, credential-shaped values, and caller-supplied known sensitive
  values fail before output.

## Verification

- Python compileall: pass.
- Focused packet suite: 17/17 pass in 10.418 seconds.
- Packet plus Shadow lifecycle/selection/opening/readiness/live-marking/proof regressions:
  168/168 pass in 93.897 seconds.
- Full Python discovery: 1,034/1,034 pass in 212.792 seconds.
- First full-discovery attempt: 1,033/1,034 with only the existing installer-path test
  failing because the separate worktree lacked `.venv`; an ignored junction to the
  existing environment satisfied that checkout-shape prerequisite, and the isolated
  test plus full rerun passed.
- `git diff --check`: pass.
- Static forbidden-import/method scan: pass.
- Source-file nonmutation and write-once rollback proof: pass.
- No .NET/WPF test was required because no .NET or WPF file changed.

## Explicit Boundary Answers

- Does this cause Codex to participate in trading? **No.**
- Does this change Monday's runtime? **No.**
- Can it modify a trade or lifecycle event? **No.**
- Can it contact Schwab? **No.**
- Can it expose credentials or full account identity? **It fails closed on defined
  secret risks and accepts caller-supplied known-sensitive values for exact scanning.**
- Can identical source evidence produce conflicting packets? **No; it produces the
  same identity and byte-identical outputs.**
- Is it ready for a later optional post-trade Codex reviewer? **Yes, after integration;
  the reviewer remains a separate optional downstream task.**

## Remaining Risk

- The packet can report only evidence the current schemas persist; it marks absent
  ideal results, system downtime, and other optional context as missing.
- Source records without the current verifiable activation/policy contract fail closed.
- Integration must be rebased only through an ordinary safe reconciliation after
  Monday's canonical operational evidence is preserved; no reset, rebase, or force push
  is authorized.
