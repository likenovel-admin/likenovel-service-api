# LikeNovel Dot MCP operator

Implementation date: 2026-10-11. This document describes the code contract.
Creation of this file does **not** mean that production deployment, OAuth
connection, or Dot schedules have succeeded. Verify each cutover gate below.

The owner authorized unattended changes to the existing five direct
recommendation slots and the three paid main single slots, with reports in the
Dot. This standing authorization replaces the former proposal-only workflow for
these operations. It does not authorize other CMS operations or email.

| Operation | Asia/Seoul cadence | Behavior |
|---|---|---|
| General direct slots | Daily 10:00 | Review factual and editorial evidence; apply only justified changes; otherwise record no change |
| Paid single slots and copy | Monday/Thursday 10:05 | Rotate three distinct eligible paid works with validated Gemini copy |

## Server contract

The existing backend hosts the official Python MCP SDK's stateless Streamable
HTTP transport at `/mcp`. The SDK session manager runs in the backend lifespan.
Existing API routes have precedence over the final MCP mount.

The server has seven tools: direct snapshot, guarded direct apply, single-copy
generation start, job status, guarded three-slot single apply, operator status,
and public readback. There is no arbitrary SQL, shell, file, product-publication,
payment, user-management or email tool.

OAuth is authorization code + PKCE S256 through the MCP's own authorization
server. Its issuer is the API origin, and its protected resource is the exact
`/mcp` URL. A single provided public client, `likenovel-dot-mcp`, uses token
endpoint authentication `none`. Dynamic registration is disabled. Register the
**exact callback shown by the ChatGPT connection form**, without wildcard
redirects. The SDK validates redirect URI, PKCE, scopes and authorization-code
expiry; the provider enforces single-use codes and rotates refresh/access tokens.

The login page verifies the existing CMS administrator through the established
Keycloak keep-sign-in client. It requests a Keycloak offline grant, verifies the
existing issuer/audience/signature/introspection path, and checks the exact
configured administrator plus the database admin role. The production identity
server verified offline refresh support on 2026-10-11; the temporary test session
was explicitly revoked afterward. No new Keycloak client/scopes, administrator
recovery, or broader realm-management permission is required.

ChatGPT receives resource-bound opaque MCP tokens with `likenovel.mcp.read`,
`likenovel.mcp.write` and `offline_access`. The server stores token hashes and
keeps upstream identity tokens encrypted using Fernet. The CMS password is
submitted only to the first-party login endpoint, never stored, never sent to the
Dot, and never returned by tools. The login form enforces its exact Origin,
CSRF-cookie binding, bounded request bodies and a shared attempt limit. Login
flows expire in ten minutes, authorization codes in one minute, MCP access in
five minutes, and rotating refresh tokens in thirty days.
Refresh rotation keeps already-issued access valid until its existing expiry,
so concurrent connector requests do not invalidate each other. Refresh tokens
remain single use, and grant revocation immediately rejects every access token.

Every MCP access validates active identity authorization and the current admin
role. The grant is bound to the configured resource, subject and client.
Revocation immediately disables the grant and erases stored identity tokens;
upstream session cleanup is attempted and its failures are logged without secret
contents. OAuth records cannot be accessed through operation-status tools.

## Persistent configuration and receipts

The default configuration path is
`/home/ln-admin/likenovel/mcp/config.json`, outside release directories.
`LIKENOVEL_MCP_CONFIG_FILE` can override it for tests or separate environments.
The file must be mode 600 in a mode-700 directory. Fields:

```json
{
  "resource": "https://api.likenovel.net/mcp",
  "issuer": "https://auth.likenovel.net/realms/likenovel",
  "allowed_subject": "<exact Keycloak admin subject>",
  "environment_db_host": "<exact production DB host from existing settings>",
  "state_db": "/home/ln-admin/likenovel/mcp/receipts.sqlite3",
  "rotation_state_file": "/home/ln-admin/likenovel/mcp/rotation-state.json",
  "oauth_callback": "<exact ChatGPT callback>",
  "token_encryption_key": "<generated Fernet key; private>",
  "writes_enabled": false
}
```

If the configuration file is absent, the MCP mount is absent. An issuer mismatch
does not enable the production mount in another environment. Invalid
configuration disables only MCP with an explicit error log; existing APIs
remain available. A DB-host mismatch also disables the
mount so the shared production configuration cannot activate against the DEV
database. The runtime kill switch is
`writes_enabled=false`; tools re-read it before writes.

SQLite uses WAL and synchronous FULL to retain generation, intent and completion
receipts across requests and releases. The daily receipt key prevents duplicate
applications. Receipts are bound to the configured admin. Intent is persisted
before CMS mutation. If a response is lost after commit, a repeated apply checks
actual state against the intended result. A mismatch blocks replay.

Direct updates lock the CMS rows, compare the entire snapshot, revalidate
eligibility, and call the existing CMS service in one transaction. Slot names,
order and exposure metadata are preserved.

Single updates require three current positions and no future reservations or
finite exposure end. They preserve names and positions, call the official
publish-now service for all three positions in one transaction, and verify the
result before commit. New history rows retain rotation history. No raw SQL
single-slot write is performed by the MCP module.

The copy core was migrated from the existing local single-slot job. It preserves
paid/all-ages/ongoing/public eligibility, real CDN-cover fingerprints and image
checks, recent-repeat exclusion and random rotation, Gemini completion checks, exact source evidence, and
two-line 8–24-character copy validation. Existing OpenRouter credentials are
read from the backend environment; credentials are never returned to the Dot.
Carry over the existing `last_proposed_at` state to the rotation state file once.

Publication age, views and bookmarks do not determine the single-slot ranking.
Candidates shown or proposed in the preceding seven days are excluded, and all
remaining works are shuffled equally. A validated Gemini proposal is recorded
before `ready`, so failure to apply does not lose its cooldown. Do not backfill
an insufficient set with recent works. Direct snapshots expose seven KST calendar
days of newly added works from this administrator's completed MCP receipts; a
fresh apply rejects re-adding a recent work absent from all current slots.
Keeping current works is not a new recommendation. Legacy unexecuted local direct
proposals remain unknown; Dot notes must also track proposals it only discussed.

Generation is asynchronous within the API process and saves its completed result
before apply. A process restart during generation can leave a `generating`
receipt; it must be reported as interrupted, not as success or no candidates.
Do not clear an uncertain `applying` receipt and blindly rerun a write.

## Cutover gates

1. Run `python -m unittest discover -s tests -p test_likenovel_mcp.py -v`,
   existing slot tests and required backend deployment checks. Build the wheel.
2. Configure the exact ChatGPT callback, allowed CMS administrator, generated
   encryption key and preserved rotation state in the protected server file.
3. Create server configuration with writes disabled; use the existing DEV/PROD
   backend deployment runbook and full runtime gates.
4. Verify public resource/OAuth discovery, unauthorized rejection and the real
   administrator's authorization-code login, PKCE, refresh and revocation.
5. Create and install the personal ChatGPT MCP plugin with its provided client
   ID, exact resource URL and scopes. Complete any required one-time security
   authorization. Configure automatic execution of these specific tools.
6. Ask the user's Dot to save both recurring operator schedules and the daily
   briefing through its cloud scheduler. Re-read exact IDs, timezone, schedule and
   enabled state through its saved-automation list. A chat acknowledgment alone
   is insufficient. Dot-owned schedules may be listed separately from the
   standalone Scheduled UI; do not duplicate across these stores.
7. Confirm an actual read-only scheduled wake and report in Dot. Enable writes
   only after authenticated reads, saved schedules and report delivery are
   verified. Do not force CMS writes outside the approved cadence. The first
   natural apply remains pending until due and must be reported as such.
8. Pause old local automation `10` and `main-single-slot-paid-proposals` after
   these setup gates, preserving their prompts/state. At the first natural
   operator run, verify committed and public results separately.

Reports must distinguish committed state from public exposure and include actual
titles, removed/added works, positions and the resulting single-slot copy.
Report the daily general-slot result briefly even on unchanged days; report
single-slot rotations with their actual titles and copy. Proactively suggest
operational opportunities, upcoming expirations, incomplete banners, failures
and decisions, using only connected and verified data. Do not repeat a retained
work as a new proposal. Expanded AI-reader/mail/promotion/banner/paid-conversion
operations need a direct user command or approval of a concrete plan; standing
slot authorization does not grant those operations. A specific direct command is
itself authorization, so do not demand a duplicate confirmation.

Rollback: disable writes, pause the new Dot schedules, disconnect the plugin,
and resume the preserved local proposal jobs. Keep receipts and prior CMS
history. Use the existing backend deployment rollback runbook if code rollback
is required; do not alter unrelated CMS content.
