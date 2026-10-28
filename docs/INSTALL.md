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
401. The token authorizes full customer administration independently of the browser
login; there are no tenant boundaries. Rotating it requires updating the environment and restarting
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

The first database operation (including account setup or the login page) applies
pending migrations transactionally.
Migration 1 creates `customers` (`id`, `name`, `email`, `address`, nullable
`vat_identifier`, `archived`) and records its version in `schema_migrations`.
Migration 2 adds `administrator` (one username and salted scrypt password hash),
`web_sessions` (hashed opaque session token, CSRF token, authentication state and
expiry), and `login_limit` (persistent shared attempt counter). No customer columns
are changed. Existing unrelated tables are preserved. Migrations are append-only and repeated
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


## Nederlandstalige webapp en beheerdersaccount

De webapp gebruikt server-side HTML en CSS, zonder JavaScript-framework, extra
services of nieuwe Python-dependencies. Python 3.12, SQLite en één Uvicorn-worker
volstaan voor de beoogde Ubuntu 24.04-server met 1 CPU / 1 GB RAM. Capaciteit onder
productiebelasting is nog niet gemeten; voer een beveiligingsreview uit vóór
gebruik met echte klantgegevens.

Stel eerst het permanente databasepad in en maak het account **op de server** aan:

```bash
export MINIBIRD_DATABASE_URL=sqlite:////var/lib/minibird/minibird.sqlite3
.venv/bin/python -m minibird.admin
```

Maak `/var/lib/minibird` vooraf aan als de servicegebruiker en beperk de toegang
(bijvoorbeeld directorymodus 700 en `umask 077`). Gebruik hetzelfde databasepad
voor accountbeheer en de webserver. De opdracht vraagt interactief om de
gebruikersnaam en tweemaal het wachtwoord (12–256 tekens). Er zijn geen standaard-
credentials en er is geen openbare registratie. Geef wachtwoorden nooit als
commandoregelargument of via een URL door. Ze worden met scrypt (N=16384, r=8,
p=1, circa 16 MiB werkgeheugen) en een willekeurige salt gehasht opgeslagen.

Voer dezelfde opdracht opnieuw uit om het account of wachtwoord te wijzigen.
Dit vervangt het enige beheerdersaccount en trekt alle bestaande sessies in.
Het is ook de herstelprocedure bij een vergeten wachtwoord. Stop tijdens deze
handeling bij voorkeur de webserver. Backups bevatten wachtwoordhashes en
sessiemateriaal; bewaar ze versleuteld of met gelijkwaardige toegangsbeperking.

Voor **uitsluitend lokale ontwikkeling via HTTP**:

```bash
export MINIBIRD_DEV_HTTP=1
.venv/bin/python -m uvicorn minibird.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Bezoek `/login` of open de hoofdpagina in de browser. Na inloggen kun je klanten
bekijken, toevoegen en wijzigen. Vanuit het detailscherm archiveer je een klant;
gegevens blijven bewaard. Het overzicht biedt een filter voor het archief en
paginering per 50 klanten. **Uitloggen** trekt de sessie direct in. Onjuiste invoer
wordt op de server geweigerd; het formulier behoudt je invoer zodat je die kunt
corrigeren. De JSON-hoofdpagina voor API-clients en `/health` blijven beschikbaar.

### HTTPS en sessiebeveiliging

Laat `MINIBIRD_DEV_HTTP` in productie **on-ingesteld**. De standaardcookie heet
`__Host-minibird`, met `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/` en zonder
`Domain`. De expliciete ontwikkelmodus gebruikt een andere cookienaam zonder
`Secure`; zet die modus nooit aan op een publiek toegankelijke server.

Plaats voor productie een HTTPS-reverse-proxy (bijvoorbeeld Caddy of nginx) voor
de Uvicorn-server op loopback. Laat alleen de proxy publiek luisteren, redirect
HTTP naar HTTPS en stel HSTS in op de proxy nadat HTTPS goed werkt. Vertrouw
forwarded headers uitsluitend van de eigen proxy; stel geen brede proxytrust in.
Log geen requestbodies, wachtwoorden, cookies of Authorization-headers. Beheertokens en sessietokens staan nooit in URLs of browser-HTML;
CSRF-tokens staan uitsluitend in de bijbehorende formulieren. De bestaande bearer-token-API
blijft afzonderlijk werken: een websessie geeft geen toegang tot `/customers`, en
een API-token logt niet in op de webinterface. Een browserbeheerder heeft de
variabele `MINIBIRD_ADMIN_TOKEN` niet nodig.

Sessies zijn willekeurige, server-side opgeslagen tokens; in SQLite staat alleen
de SHA-256-hash van het cookie-token. Een ingelogde sessie verloopt na acht uur
zonder automatische verlenging. Het inlogformulier gebruikt een anonieme sessie
van vijftien minuten voor CSRF-bescherming. Inloggen roteert het sessietoken;
uitloggen en accountwijzigingen trekken sessies in. Alle muterende webformulieren,
ook inloggen en uitloggen, vereisen het bijbehorende CSRF-token. Verlopen
formulieren moet je vernieuwen. De webpagina's worden niet gecachet, staan geen
framing toe en gebruiken een restrictieve Content Security Policy.

De inloglimiet geldt gedeeld voor het enige beheerdersaccount, onafhankelijk van
gebruikersnaam of IP-adres: maximaal vijf pogingen per vijf minuten. Ook herstarten
of een nieuwe browser omzeilt die limiet niet. Daarna volgt HTTP 429 met
`Retry-After`. Deze eenvoudige bescherming kan tijdelijk ook de echte beheerder
blokkeren; wacht tot het venster voorbij is. Een vertrouwde reverse-proxy kan
extra verbindingslimieten toevoegen. Dezelfde foutmelding wordt gebruikt voor
onbekende gebruikers en onjuiste wachtwoorden.

### Upgrade en rollback van de webapp

Stop de server en maak een backup zoals hierboven beschreven. Installeer deze
versie, voer accountbeheer uit op **de bestaande database** en start de server
opnieuw. Migratie 2 bewaart alle klanten, IDs en archiefstatussen. Controleer login,
een bestaande klant en desgewenst de bearer-API. De automatische tests controleren
ook de upgrade vanaf schema 1 en het gegevensbehoud.

Een oudere klanten-API-versie weigert schema 2: alleen de code terugzetten is dus
onvoldoende. Herstel bij rollback de pre-upgrade databasebackup én de bijpassende
codeversie. Bewaar eerst een aparte kopie van de huidige database; herstel kan
latere wijzigingen verliezen. Pas nooit handmatig migratieversies aan.

Controleer de installatie met `.venv/bin/python -m pytest -q`. Tests gebruiken
alleen tijdelijke databases en fictieve klanten; ze versturen geen e-mail.
