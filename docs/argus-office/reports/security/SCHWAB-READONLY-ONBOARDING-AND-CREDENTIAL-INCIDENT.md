# Schwab Read-Only Onboarding And Credential Incident Record

Status: historical evidence; read-only integration active; transmission unavailable

This report preserves the detailed Schwab onboarding, loopback-certificate, OAuth,
credential-containment, account-discovery, validation, and immutable-binding history
that was previously embedded in the live Roadmap.

## Vendor Capability

- Schwab Trader API Support confirmed that Trader API cannot access thinkorswim
  paperMoney and that no retail sandbox is available.
- FakeBroker therefore remains the only automated execution boundary.
- thinkorswim paperMoney is limited to manual ticket and fill-model reconciliation.
- The eventual broker direction remains Schwab read-only plus separately supervised
  live canaries. No interim Alpaca implementation is approved.

## Developer Application

- Schwab approved `Trader API - Individual`.
- Application: `Market Intelligence Workstation`.
- Products: `Accounts and Trading Production` and `Market Data Production`.
- Callback: `https://127.0.0.1:8182/oauth/callback`.
- Registered order-request throttle: `5` per account per minute.
- Application registration and product entitlement do not authorize Momentum Hunter
  to transmit an order.

## Loopback And Certificate Boundary

- SCHWAB-001 implements a one-use TLS 1.2-or-newer HTTPS listener restricted by default
  to `127.0.0.1:8182/oauth/callback`.
- It validates path, host, state, method, timeout, and one-use semantics; suppresses
  request logging and secret-bearing representations; and closes after success,
  terminal rejection, malformed handling, manual close, or timeout.
- The certificate lifecycle creates a local root and loopback-only leaf, encrypts the
  leaf key, stores its password with current-user DPAPI, applies current-user-only ACLs,
  validates chain/hostname/hashes, and requires exact install/remove confirmations.
- Production-local certificate version:
  `20260725T004100Z-feaa7bc59097`.
- Root SHA-1:
  `E35BB94F68A98BFCADB6E69ACD63961BBE3AA76F`.
- Root SHA-256:
  `C926D9F89B5E5D11BF3179B04D4D7928A0325AD8514064E9658D05BB8045BEA1`.
- Leaf SHA-256:
  `74B38DE72175834B325EDDF17C9BA1A934543A525D7831A609C2876BC618DA3E`.
- Steven physically verified the exact Windows trust warning. Chrome completed the
  synthetic callback without a privacy interstitial, and port `8182` closed after the
  one-use response.

## Credential And OAuth Onboarding

- SCHWAB-002 added exact authorization/token contracts, hidden credential entry,
  current-user DPAPI storage, explicit current-user ACLs, token exchange/refresh,
  redacted status/errors, and encrypted immutable storage for a future account binding.
- It exposed no account or order endpoint and no transmitting broker method.
- The first live authorization safely stored no token after the original callback
  window expired. The corrected ten-minute path has regression proof.
- Steven completed the corrected authorization and selected only the intended
  low-value Individual account.

## Credential Incident And Containment

- During authenticated portal research, Schwab's expired-session DOM retained the
  revealed Client Secret and exposed it to the browser-automation channel.
- Exact in-memory comparison against tracked files found no Client ID or Client Secret
  in Git.
- The old local authorization material was removed and the application was temporarily
  deactivated before a replacement path was proven.
- Schwab provides no self-service Client Secret rotation. A replacement app was blocked
  because the Individual product slots were already consumed by the existing app.
- Under Steven's direction, the existing approved application was reactivated.
- Masked-copy controls transferred the original values directly to temporary
  current-user DPAPI staging without displaying the secret. Momentum Hunter restored
  the normal DPAPI vault, verified it, removed the temporary encrypted duplicate, and
  cleared the clipboard.
- Ciphertext contained neither plaintext value and retained one explicit Full Control
  ACL entry for `BEASTCOMPUTER\steve`.
- A fresh OAuth flow then succeeded. The callback process exited and port `8182` closed.

No Client Secret rotation occurred. Current read-only use continues under the recorded
accepted risk. Transmitting code is blocked until Schwab rotates the secret, permits a
replacement app, or explicitly supplies acceptable vendor-side remediation.

## Read-Only Account Isolation

- SCHWAB-003 exposes only the account-number/hash discovery GET and rejects redirects,
  malformed or oversized responses, missing fields, invalid suffixes, duplicate
  identities, and unexpected account counts.
- The authorized live discovery returned exactly one account ending `2573`.
- Account-detail validation performs one read-only detail GET without a positions
  request, verifies official type `CASH`, rejects any position, suppresses balance
  values, and persists nothing.
- The pre-binding pass maps official `CASH` only to internal `INDIVIDUAL_CASH`.
- The immutable binder re-runs the identity chain before saving through current-user
  DPAPI and refuses replacement before token or network access.
- The bound-refresh path rotates tokens in memory, revalidates exact hash, suffix,
  `CASH` type, and no-position state, and stores tokens only after every check passes.
- The encrypted binding is `PINNED`, `INDIVIDUAL_CASH`, and
  `ENCRYPTED_DPAPI_IMMUTABLE`.
- Order transmission remains `UNAVAILABLE`.

## Verification Evidence

- SCHWAB-001 synthetic listener proof: focused tests `19 / 19`; full Python discovery
  `653 / 653`.
- Production certificate trust proof: focused Schwab tests `47 / 47`; full Python
  discovery `672 / 672`.
- SCHWAB-002 onboarding proof: focused tests `60 / 60`; full Python discovery
  `702 / 702`.
- SCHWAB-003 discovery proof: focused tests `13 / 13`; bounded Schwab suite `82 / 82`.
- Post-binding proof: bounded Schwab tests `123 / 123`; full repository tests
  `756 / 756`.
- Exact scan of 573 tracked files found no live application ID, application secret,
  access token, refresh token, or account hash.

## Remaining Gates

- Do not request a Schwab username, password, or MFA.
- Do not place a Client ID, Client Secret, token, or account hash in Git or chat.
- Do not automate thinkorswim.
- Do not add broker preview unless official documentation proves it cannot transmit.
- Split the first live progression into a broker-plumbing canary and a later
  strategy-driven canary.
- Before a plumbing canary, define pre-canary zero positions, canary-active only the
  exact ledger-matched position, and post-canary return to zero positions.
- Prove settled-cash checks, ambiguous-submit handling, retries, partial fills, cancel
  races, restart reconciliation, shutdown, and independent revocation.
- A real order remains an explicit Steven consequence gate.
