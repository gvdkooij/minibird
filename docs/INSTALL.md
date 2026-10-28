# Development installation (Ubuntu 24.04)

Install Python 3.12, Python venv and git. Clone the repository, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
uvicorn minibird.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/health on the same machine.

This is a development server, not a production deployment. Do not expose it publicly or use real financial data yet.

## Customer management (development MVP)

Customer routes require a single-operator administrator bearer token. Generate one
with `python -c 'import secrets; print(secrets.token_urlsafe(48))'` and supply it as
`MINIBIRD_ADMIN_TOKEN` in the server process. Keep it secret; do not commit it or
share it between users. Tokens shorter than 32 characters or missing configuration
close all customer routes with HTTP 503. Invalid or missing credentials return
401. The token authorizes full customer administration; there are no user accounts
or tenant boundaries. Rotating it requires updating the environment and restarting
the server. `.env` files are not loaded automatically.

Set `MINIBIRD_DATABASE_URL=sqlite:///./data/minibird.sqlite3` (the default) or use
`sqlite:////absolute/path/minibird.sqlite3`. Use a persistent file, not `:memory:`.
Keep the database directory accessible only to the service account. Run on loopback;
remote access requires an independently secured TLS deployment. Use fictional data
until authentication and production deployment have been reviewed.

The API workflow is available in `/docs` using **Authorize** with the administrator
token. All `/customers` routes require authorization:

1. `POST /customers` with JSON fields `name` (person or company, 1–200 characters),
   `email` (valid address, at most 254 characters), `address` (1–2000 characters),
   and optional `vat_identifier` (at most 64 characters). Returns 201 with the ID.
2. `GET /customers` lists active records in ID order. Use `limit` (1–500, default
   100), `offset` (default 0), and `include_archived=true` as needed.
3. `GET /customers/{id}` views a record, including an archived one.
4. `PUT /customers/{id}` replaces the four editable fields. Omitted VAT becomes
   null. IDs and archive state cannot be supplied. Invalid input returns 422;
   missing records return 404.
5. `POST /customers/{id}/archive` hides a record from the default list without
   deleting it. Repeating this operation is safe. Archived records remain
   viewable and editable; editing does not unarchive them.

Input is trimmed and unknown fields are rejected. VAT identifiers are stored as
provided; tax authority verification is outside this MVP. No emails are sent.

## Schema, upgrades, backups and rollback

The first authorized database operation applies pending migrations transactionally.
Migration 1 creates `customers` (`id`, `name`, `email`, `address`, nullable
`vat_identifier`, `archived`) and records its version in `schema_migrations`.
Existing unrelated tables are preserved. Migrations are append-only and repeated
startup does not recreate or clear customer records. Unsupported newer or
non-contiguous versions are rejected rather than downgraded.

Before upgrading, stop the server and back up the SQLite file to a secure location
outside the checkout. Install the new application version, restart with the same
database path and token, and make an authenticated `GET /customers` request to
apply and verify the upgrade. Retain the backup until verification is complete.

For rollback, stop the server, restore the matching previous application version
and its pre-upgrade database backup, then restart and verify. Do not manually
remove migration versions or drop tables. Restoring a backup loses changes made
after that backup; preserve the current database separately before restoring.
Migration 1 only adds tables, so returning to the foundation version leaves those
tables intact but removes access to the customer API.
