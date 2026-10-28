# MiniBird

Open-source, self-hosted invoicing software.

Status: early development; do not use with real financial records yet.

## Roadmap
1. Reproducible project foundation and CI
2. Customer management
3. Quotes and invoices
4. PDF generation and SMTP

Changes are developed on feature branches and reviewed through pull requests.

Customer management now provides an authenticated development API with SQLite
persistence, validation and non-destructive archiving. See
[installation and customer workflow](docs/INSTALL.md) for configuration, migrations,
backups and rollback. Production authentication review remains required before
using real customer data.
