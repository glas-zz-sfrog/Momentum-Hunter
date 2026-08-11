# ARGUS-SHADOW-025J Goal Charter

## Goal

Add a dormant, deterministic security contract that rejects an installed
continuous-evidence root unless supplied Windows path, ownership, reparse, and
effective-access evidence proves a distinct least-privilege writer boundary.

## Operator Value

Momentum Hunter must not claim that ACLs protect its raw evidence when Engine
Host and WPF run under the same Windows identity. Installation needs an
explicit fail-closed gate for root location, traversal, ownership, inherited
access, writer rights, nonwriter mutation, and ancestor replacement risk.

## Scope

- Freeze a versioned root-security policy and evidence snapshot.
- Require an absolute local root beneath one approved base.
- Require complete component evidence from volume root through target root.
- Reject missing, file-shaped, symlink, or reparse components.
- Require trusted ownership and a protected root DACL.
- Require exact effective-access evidence for writer, interactive, and broad
  principals at every component.
- Require a distinct writer SID with only the rights needed for append and
  atomic replacement.
- Reject nonwriter root mutation and ancestor replacement authority.
- Return a fingerprinted contract result that never authorizes activation.

## Non-Goals

- No filesystem or ACL inspection, directory creation, ownership/permission
  change, Windows account creation, installed-root selection, service identity
  change, Engine Host import, provider/account call, broker/order capability,
  Paper/Shadow activation, merge, or install.

## Acceptance Evidence

- Compileall passes.
- Focused same-SID, owner, writer-right, inheritance, broad-access, ancestor,
  reparse, malformed-evidence, tamper, and non-capability tests pass.
- Adjacent runtime-boundary and full Python discovery pass.
- Source inspection proves the current service launches Engine Host under its
  own current-user identity rather than a distinct principal.
- Diff, protected-path, credential, capability, generated-artifact, and
  canonical nonmutation reviews pass.

## Classification

`IMPLEMENTED_PENDING_MERGE`
