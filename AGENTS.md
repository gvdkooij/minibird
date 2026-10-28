# MiniBird development rules

MiniBird is a self-hosted, open-source invoicing application. Keep it runnable on Ubuntu 24.04 with 1 CPU and 1 GB RAM.

## Workflow
- Work on a dedicated branch per issue; never commit features directly to main.
- Keep changes small and focused. Open a pull request with test evidence.
- Add or update automated tests for every behavior change.
- Do not delete or change existing features without explicit approval.
- Keep dependencies minimal and pin released dependency versions.
- Use database migrations for schema changes. Preserve user data.
- Never commit credentials, real customer data, or production database files.
- Never silently change financial totals, invoice numbers or historical records.
- Use integer minor currency units or Decimal; never binary floats for money.
- Require authentication and authorization before handling customer data.
- Treat imports and uploads as untrusted input.
- Never send real emails during tests.
- Document installation, upgrades, backups and rollback steps.
- Do not claim tests passed unless they were actually run.

## Definition of done
Tests pass, documentation is updated, security implications reviewed, and the feature works on a clean install.
