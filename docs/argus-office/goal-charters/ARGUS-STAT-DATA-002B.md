# ARGUS-STAT-DATA-002B Goal Charter

## Objective

Repair the confirmed canary orchestration boundary so transient Continuous
runtime/checkpoint state remains under the Windows temporary directory and all
acquired writer resources are explicitly released on every failure path.

## Authorized Scope

- Allocate one unique `%TEMP%` runtime root per canary attempt.
- Keep the prospective denominator at its separately authorized durable root.
- Close runtime, writer, and capability resources before forensic export.
- Hash-verify an immutable `FORENSIC_COPY_ONLY` export, then retire the
  disposable runtime root.
- Add deterministic initialization, mid-runtime, shutdown, ownership-release,
  packaging-order, restart, export, and persistent-root rejection tests.
- Rehearse the exact resource/checkpoint/restart/export/package path offline.
- Run one same-day natural regular-session canary only after all offline proof
  and Hard Chew gates pass and enough safe market time remains.

## Prohibited Changes

Do not change population definitions, prospective identity, anti-hindsight,
historical floors, denominator semantics, discovery, readiness, composition,
TradePlans, strategy, scoring, provider semantics, Paper, Shadow, broker,
account, position, order, service, scheduler, or canonical production behavior.

## Acceptance

1. Runtime checkpoint state is created only beneath `%TEMP%`; durable checkpoint
   authority remains prohibited.
2. Every successfully acquired writer/capability is explicitly closed on
   initialization failure, runtime failure, restart, and normal shutdown.
3. Physical writer ownership can be reacquired after every tested cleanup path.
4. Packaging cannot begin before verified resource release and forensic export.
5. Source and destination manifests match, the export is evidence-only, and the
   temp root is retired only after verification.
6. Exact-path offline normal and injected-init-failure rehearsals package and
   verify successfully.
7. Focused tests, full approved-environment discovery, compile, scans, and
   protected-boundary review pass before provider contact.
8. Every terminal live-canary outcome produces a sanitized verified ZIP and
   stops for independent review.
