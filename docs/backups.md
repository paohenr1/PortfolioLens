# PostgreSQL backup and restore

The repository provides a private custom-format export and a disposable recovery drill.
It uses PostgreSQL's own tools and the existing database; there is no paid backup
service, automatic upload, production restore or scheduled job yet.

## Export

Use a dedicated private directory and a new filename. The command refuses an
existing file or symlink, creates the archive with mode 0600, obtains a consistent
`pg_dump` snapshot, flushes it and checks that `pg_restore --list` can read its
table of contents. A failed/interrupted export removes only its own partial file.
Table-of-contents validation is not a full recovery test.

For the recognized local development container, after the existing PostgreSQL helper and
migrations:

```sh
install -d -m 0700 .local/backups
uv run --frozen --env-file .local/database.env python manage.py backup_database --local-container --output .local/backups/manual-new-name.dump
```

This is an optional real development-data export, not part of ordinary startup. The
container mode verifies checkout label, expected mounts, image digest, running state,
private network/socket, process user and absence of TCP port publishing. It cannot
silently select a different Docker daemon, container or database host.

For a separately configured PostgreSQL target, install `pg_dump`/`pg_restore`
matching its server major version and omit `--local-container`. The configured
connection, TLS mode and CA path are passed through PostgreSQL client settings;
passwords stay in the child environment, not argv, files or messages. Production
configuration still requires `verify-full`; do not weaken TLS to export a backup.
The target must be explicitly configured before using this path.

Archives contain private account/portfolio data, password hashes and sessions. Keep them
outside source control; `.local` and `*.dump` are ignored. File permissions do not
encrypt an archive. On the selected host, configure encrypted off-machine copies,
retention and access controls, and check applicable stored reference-data rights. No
scheduled off-machine backup destination is configured by the repository.

## Isolated recovery drill

```sh
uv run --frozen python scripts/verify_backup_restore.py --local-container
```

The drill creates two randomly named `test_stock_backup_<uuid>_a/b` databases
using only the isolated local test role, which cannot connect to development
storage. It migrates the source, inserts labeled synthetic accounts, portfolios,
trades, a dividend/split, fee correction/audit, watchlists/preferences/bookmarks,
sessions and both quota rows. No live provider transport is enabled.

It runs the actual export command and restores into the second empty generated
database with `pg_restore --exit-on-error --no-owner --no-acl`. Every model's
ordered row digest/count (including many-to-many tables) and migration-history
digest must match before further
functional checks. Those checks independently confirm 16 shares, 80.80 USD
remaining FIFO basis, 10.80 USD realized sale gain and 932 USD cash, plus password
verification, group/user permissions, decoded sessions with the same separately
provisioned application secret, original/replacement correction links, watchlist preferences,
journal immutability and another owner's private 404/no-store responses.

Cleanup verifies the exact database OID and owner recorded at creation before dropping
either generated database. Changed identities are left untouched and reported. Temporary
synthetic archives/manifests are removed.

## Production recovery procedure

For the chosen deployment, recover into a newly created isolated database with
appropriate role grants, restore a trusted archive, compare records/schema and
run private/accounting smoke checks before switching application configuration.
Do not restore over an active database or use an archive from an untrusted source;
restoring a PostgreSQL archive executes its SQL. This release exposes no command
that overwrites the active application's database.

This is a single-database logical backup. Roles, ownership/grants, secrets,
hosting configuration and filesystem/static outputs need separate provisioning.
The dump/restore intentionally omits ownership and ACL commands; recovery roles
must be supplied by the operator. A local successful drill does not prove hosted
storage durability, off-site recovery, scheduled retention, point-in-time recovery
or a recovery-time objective. Repeat the drill and record timing on the actual
private deployment target before making those claims.
