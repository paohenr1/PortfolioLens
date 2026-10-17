# Contributing

Read [setup](docs/setup.md), [architecture](docs/architecture.md), and the relevant
[methodology](docs/methodology.md) before changing behavior. Start a focused branch
from current `main` and keep each commit understandable on its own.

## Change boundaries

- Preserve owner isolation, CSRF, idempotency, immutable journal history and
  corrected-history validation.
- Keep provider access separate from financial calculations and presentation.
- Preserve exact numeric inputs and documented rounding; do not fill missing
  financial observations with invented values.
- Explain changed assumptions, source fields, limits and unavailable states.
- Use migrations for schema changes and review existing-data compatibility.
  Do not run development tests or fixtures against production databases.
- Avoid new frameworks or dependencies unless the change requires them.

## Validation

Run Ruff, Django checks and the affected tests using the commands in
[setup](docs/setup.md#automated-checks). Financial changes need independent
examples and relevant edge cases; authorization/storage changes need PostgreSQL
integration coverage. Use browser checks for navigation or interaction changes.
Do not weaken existing tests to accommodate an unintended behavioral change.

Ordinary tests must not require live provider credentials. Report PostgreSQL
skips, unavailable environments and unrun live checks explicitly. Live acceptance
is opt-in and uses bounded provider requests.

## Pull requests

Describe the concrete problem, resulting behavior and validation. Include
methodology or migration implications when relevant. Write for a reviewer who
has not seen the development conversation. Keep PRs focused; list meaningful
limitations rather than historical task logs.

Documentation should explain current product behavior, setup, usage, architecture,
methodology and operations. Keep conversation history, private handoffs, personal
context, credentials, private datasets and approval exchanges out of the repository.

Merging source does not establish deployment readiness. A release requires
verification of the selected hosting branch, intended commit, configuration and
applicable data rights; see [operations](docs/render-deployment.md).
