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


## Webinterface

MiniBird heeft nu een Nederlandstalige webinterface voor klantenbeheer: inloggen,
klanten bekijken, toevoegen, wijzigen en archiveren. Maak het enige
beheerdersaccount lokaal aan met `python -m minibird.admin`. Zie de
[installatiehandleiding](docs/INSTALL.md#nederlandstalige-webapp-en-beheerdersaccount)
voor het databasepad, lokale HTTP-ontwikkeling en verplichte HTTPS-configuratie
voor productie. De bestaande bearer-token-API blijft beschikbaar.

Wachtwoorden worden gehasht opgeslagen. De webapp gebruikt server-side sessies,
CSRF-bescherming en een persistente inloglimiet, zonder extra services of
JavaScript-framework. Een productiereview blijft vereist vóór gebruik met echte
klantgegevens.
