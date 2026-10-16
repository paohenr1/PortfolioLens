# Repository conventions

- Keep the existing Django, PostgreSQL and server-rendered architecture.
- Separate provider I/O, financial calculations, persistence and presentation.
- Preserve owner isolation, CSRF, journal immutability, correction validation,
  idempotency and exact financial arithmetic.
- Read the relevant methodology before changing calculations. Document assumptions,
  rounding, source semantics, unavailable states and limits.
- Use the setup guide's checks; run PostgreSQL tests for storage/concurrency changes.
  Never use production data for tests or fixtures.
- Keep changes focused and commit/PR descriptions understandable without chat context.
- Keep public documentation focused on product behavior and repository conventions.
  Never commit credentials or private data.
