# Long-Running Campaign Provenance Template

Use this contract for any experiment expected to overlap production work. Create
one draft JSON record, finalize it with
`python tools/verify_campaign_provenance.py finalize <draft> <write-once-output>`,
and verify it at every closeout with `verify <write-once-output>`.

## Campaign-Frozen Identity

Record before launch:

- `taskId`
- `sourceGitHead`: lowercase full 40-character Git SHA
- `sourceFileManifestSha256`: hash of the sorted executable/dependency file manifest
- `configurationFingerprint`
- `executableSha256`
- `evidenceRootFingerprint`: identity of the approved campaign-owned root, not a secret-bearing path dump
- `providerRouteAllowlistSha256`
- `startedAt`: offset-aware timestamp
- `processIdentity.processId`, `processIdentity.executableSha256`, and `processIdentity.startedAt`

Branch names and abbreviated SHAs are labels only. They are never authority.

## Production Baseline

Record at campaign start:

- `canonicalGitHead`
- `installedProductGitHead`
- `manifestSha256`
- `observedAt`
- every relevant service name, executable SHA-256, configuration SHA-256, and deployment-manifest SHA-256

`baselineFingerprint` is computed by the finalizer. Current governance HEAD must
never be substituted for installed product identity.

## Shared Resources

Declare every resource visible to both campaign and production, including:

- config files
- credential/token state
- runtime or executable paths
- manifests and service definitions
- checkpoints and evidence roots
- research/universe inputs

Each record states `resourceId`, `resourceType`, `mutable`, `owner`,
`allowedWriters`, `campaignAccess`, `mutationRules`, and a sanitized
`baselineFingerprint`. A mutable resource without an owner/writer declaration is
a provenance failure. Read-only campaign access does not make a production-
mutable resource immutable.

## Authorized External Change

Append one ordered record for each separately authorized change:

- contiguous `sequence` and offset-aware `observedAt`
- `taskId` and concrete `authorization`
- old/new canonical full SHA
- old/new installed-product full SHA
- old/new deployment-manifest SHA-256
- affected service names
- declared shared resources touched
- isolation-revalidation result and evidence hash

The finalizer chains each record to the prior baseline/change fingerprint. Never
edit or remove an earlier change record.

## Isolation Revalidation

After every external change, verify all of these against the campaign's frozen
start evidence:

- campaign source unchanged
- campaign executable/file manifest unchanged
- campaign configuration unchanged
- campaign process identity still valid
- evidence root valid and campaign-owned
- campaign lock/state valid
- provider contract unchanged
- every shared path revalidated
- no checkpoint rewritten

All true yields `AUTHORIZED_EXTERNAL_CHANGE_ISOLATION_REVALIDATED`. Any false
yields `CAMPAIGN_ISOLATION_BROKEN`; the campaign integrity claim fails honestly.

## Separate Claims

`CAMPAIGN_NONMUTATION` means the frozen campaign source, configuration,
process, evidence, and shared-resource contract remained intact.

`GLOBAL_PRODUCTION_NONMUTATION` means no production Git, installed product,
manifest, service, scheduler, or other declared production state changed at all.

A campaign may truthfully report:

```text
CAMPAIGN_NONMUTATION = PASS
GLOBAL_PRODUCTION_NONMUTATION = FALSE
AUTHORIZED_EXTERNAL_CHANGES_PRESENT = TRUE
```

only when every external change is declared and its isolation revalidation
passes. These semantics are prospective and never repair a historical claim.

## Installed Product Identity

Every deployment evidence packet must preserve, independently of governance
HEAD:

- `installedProductGitHead`
- executable hash
- config hash
- deployment-manifest hash

If current master is later than installed product, compare every intervening
path. Only a proven governance/docs-only difference may be labeled legitimate.
