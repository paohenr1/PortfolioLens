# Accounts and authorization

This part uses Django's built-in authentication and sessions, the existing
custom user model, and local templates. It adds no dependencies, paid services,
email delivery, or provider requests. Development research pages remain public;
production now defaults to sign-in required and registration closed. See
[production serving/private access](production-serving.md).

## Workflow

1. Choose **Create account**. Supply a unique username and confirm a password.
   Passwords must have at least 12 characters and pass Django's common-password,
   numeric-password, and user-similarity checks. Successful registration signs
   in the new user and opens **My account**.
2. Use **Sign in** with the username and password. A safe return path supplied
   by a protected page is honored; otherwise the destination is My account.
3. **Change password** requires the current password and validates the new
   password. The current session stays signed in; other sessions lose access
   on their next request. A deactivated user also loses private access.
4. **Sign out** submits a CSRF-protected POST and clears the session. A GET
   cannot sign out a user. Sessions expire after eight hours of inactivity.

Email is not collected. Keep credentials in a password manager: password
recovery and email verification are not implemented. The forms state that
recovery is unavailable. No recovery claims or placeholder email deliveries
are presented. Multi-factor authentication and social login are also pending.

## Boundary and security decisions

| Route | Access and behavior |
| --- | --- |
| `/register/` | Public GET/POST; validates before creating a user; signed-in users return to their account |
| `/sign-in/` | Public GET/POST; generic credential failure; inactive users cannot authenticate |
| `/sign-out/` | POST only; session cleared; fixed destination `/` |
| `/account/` | Signed-in GET only; identity comes directly from `request.user` |
| `/password/change/` | Signed-in GET/POST; changes only the current user's password |
| `/password/changed/` | Signed-in GET/HEAD confirmation |

The account page accepts no user identifier for lookup. Supplying another
username or user ID in query parameters cannot change the displayed owner.
This proves the account boundary, not future portfolio authorization: each
private portfolio query must filter by its owner and have negative isolation
tests. The [portfolio foundation](portfolios.md) now applies owner filters and
isolation checks on PostgreSQL; ledger access uses the same owner-scoped boundary; see [ledger](ledger.md).

Django handles password hashing, password validation, constant-work handling
for unknown login usernames, authentication, session-key and CSRF-token
rotation, and password-change session invalidation. Login return destinations
use Django's same-host/HTTPS validation; registration and logout have fixed
destinations. Every modifying form includes a CSRF token. Passwords are never
repopulated into invalid forms. Authentication POST fields are marked sensitive
for production exception reports. Development debug pages are not safe for
public access; production mode disables debug.

Account responses send `Cache-Control: no-store` and related Django no-cache
headers. The existing local-assets CSP remains in place. Session cookies are
HttpOnly and SameSite=Lax; production additionally requires HTTPS and secure
session/CSRF cookies. Routine successful development-server access logging is
disabled. A future deployment must redact sensitive fields and account return
URLs in its own server/proxy logs.

If no stable `DJANGO_SECRET_KEY` is configured, development generates one per
process and sessions are invalidated at restart. Accounts remain in the local
development database. Configure a stable key through secure environment
settings when persistent development sessions are wanted; never paste it into
source, chat, or setup instructions. No extra vault requirement is needed for
the development workflow.

## Attempt limits and practical limits

Login, registration, and password-change POSTs share an atomic
budget: ten admitted attempts per direct client address and sixty total
per fixed minute, including valid and invalid attempts. Excess attempts return
HTTP 429 and a bounded `Retry-After` (1–3600 seconds; normally at most 60). GET forms and sign-out remain
available. Counter entries are admitted only with budget and retain hashed
addresses, at most sixty per window. Forwarded address headers are ignored.
There is no username-based lockout that a stranger can trigger for a victim.

Development memory counters reset on restart and each worker has its own allowance.
Production now requires shared PostgreSQL admission across workers/restarts;
storage failure returns a fixed no-store 503 before account mutation, without
memory fallback. See [release safeguards](release-safeguards.md). Fixed windows
allow boundary bursts and users sharing an address share its allowance. The global
cap can deny legitimate login attempts during an attack. Verified ingress identity,
recovery and host-specific operations still need deployment review.
Registration is open in this development application;
do not expose it publicly as a finished authentication service.

## Validation

The 28 authentication tests exercise real sessions, two-user identity
isolation, CSRF enforcement, unsafe return destinations including HTTPS
downgrades, registration validation, generic failures, inactive accounts,
password hashing, password-change behavior across sessions, POST-only logout,
private cache headers, cookie settings, sensitive POST metadata, fixed-window
recovery, and concurrent client/global budget enforcement. They use Django's
isolated test database and make no provider calls. The full suite now has 518 tests and passes on PostgreSQL.

```sh
uv run --frozen python manage.py test tests.test_authentication --verbosity 2
python3 tests/browser_authentication.py
```

The optional browser runner uses the cloud's preinstalled Playwright/Chromium.
It starts a loopback server with a temporary migrated database, creates two
test accounts, checks owner identity, password changes/re-login, sign-out,
validation, keyboard controls, and desktop/mobile overflow. It removes the
temporary database and stops its child process afterward. It makes only local
browser requests and never creates accounts in the development database.
Screenshots are under `/tmp/stock-authentication-*.png`; diagnostics are in
`/tmp/stock-authentication-server.log`. The runner is separate from normal
startup and is not yet included in GitHub Actions.

PostgreSQL and owner-scoped private portfolio metadata are now implemented.
The append-only [USD ledger](ledger.md) now uses this identity boundary.
[FIFO positions, cost basis, and realized sale gains](fifo.md) also use this
owner boundary. Recorded [dividends and splits](corporate-actions.md) also use
that boundary; [market valuation](valuation.md) now uses the same private owner checks.
