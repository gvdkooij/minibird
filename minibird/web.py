"""Small, server-rendered Dutch UI. The bearer API remains independent."""
import hashlib
import os
import secrets
import time
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from minibird.admin import hash_password, verify_password
from minibird.customers import CustomerInput, archive_customer, create_customer, database, find, update_customer

router = APIRouter()
SESSION_SECONDS = 8 * 60 * 60
LOGIN_WINDOW = 5 * 60
MAX_ATTEMPTS = 5
# Same work for an unknown username as for a valid account.
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def secure_cookie():
    return os.environ.get('MINIBIRD_DEV_HTTP') != '1'


def cookie_name():
    return '__Host-minibird' if secure_cookie() else 'minibird-dev'


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def session(request):
    token = request.cookies.get(cookie_name(), '')
    if len(token) != 64:
        return None
    with database() as connection:
        row = connection.execute('SELECT * FROM web_sessions WHERE token_hash = ? AND expires > ?', (token_hash(token), int(time.time()))).fetchone()
        return dict(row) if row else None


def new_session(response, authenticated=False, old=None):
    token, csrf = secrets.token_hex(32), secrets.token_hex(32)
    now = int(time.time())
    ttl = SESSION_SECONDS if authenticated else 15 * 60
    with database() as connection:
        connection.execute('DELETE FROM web_sessions WHERE expires <= ?', (now,))
        if old:
            connection.execute('DELETE FROM web_sessions WHERE token_hash = ?', (old['token_hash'],))
        # Bound anonymous session storage even under repeated login-page requests.
        connection.execute('DELETE FROM web_sessions WHERE authenticated = 0 AND token_hash IN (SELECT token_hash FROM web_sessions WHERE authenticated = 0 ORDER BY expires DESC LIMIT -1 OFFSET 999)')
        connection.execute('INSERT INTO web_sessions VALUES (?, ?, ?, ?)', (token_hash(token), csrf, int(authenticated), now + ttl))
    response.set_cookie(cookie_name(), token, max_age=ttl, httponly=True, secure=secure_cookie(), samesite='strict', path='/')
    return csrf


async def form_data(request):
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Ongeldig formulierformaat')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, 'Formulier te groot')
    try:
        parsed = parse_qs(body.decode('utf-8', errors='strict'), keep_blank_values=True, max_num_fields=10)
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Ongeldig formulier')
    if any(len(values) != 1 for values in parsed.values()):
        raise HTTPException(400, 'Dubbele formuliervelden')
    return {key: values[0] for key, values in parsed.items()}


def csrf_check(current, data):
    supplied = data.pop('csrf', '')
    if not current or not secrets.compare_digest(supplied.encode(), current['csrf'].encode()):
        raise HTTPException(403, 'Ongeldig of verlopen formulier. Vernieuw de pagina.')


def hidden(csrf):
    return f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'


def page(title, content, current=None, status=200):
    nav = '<a href="/ui/customers">Klanten</a>'
    if current and current['authenticated']:
        nav += f'<form action="/logout" method="post">{hidden(current["csrf"])}<button class="quiet">Uitloggen</button></form>'
    return HTMLResponse(f'''<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · MiniBird</title>
<link rel="stylesheet" href="/ui/style.css"></head><body><header><a class="brand" href="/ui/customers">◈ MiniBird</a><nav>{nav}</nav></header>
<main><p class="eyebrow">EENVOUDIG KLANTENBEHEER</p><h1>{escape(title)}</h1>{content}</main>
<footer>MiniBird · Jouw administratie, overzichtelijk op één plek.</footer></body></html>''', status_code=status)


def login_page(csrf, error='', status=200):
    return page('Welkom terug', f'''<section class="card login"><p>Log in om je klanten te beheren.</p>
<p role="alert" class="error">{escape(error)}</p><form method="post" action="/login">{hidden(csrf)}
<label>Gebruikersnaam<input name="username" autocomplete="username" maxlength="100" required autofocus></label>
<label>Wachtwoord<input type="password" name="password" autocomplete="current-password" maxlength="256" required></label>
<button>Inloggen</button></form></section>''', status=status)


def require_login(request):
    current = session(request)
    return current if current and current['authenticated'] else None


@router.get('/login')
def login(request: Request):
    current = session(request)
    if current and current['authenticated']:
        return RedirectResponse('/ui/customers', status_code=303)
    response = HTMLResponse()
    csrf = new_session(response, old=current)
    rendered = login_page(csrf)
    rendered.headers['set-cookie'] = response.headers['set-cookie']
    return rendered


@router.post('/login')
async def login_submit(request: Request):
    current = session(request)
    data = await form_data(request)
    csrf_check(current, data)
    if current['authenticated']:
        return RedirectResponse('/ui/customers', status_code=303)
    username, password = data.get('username', ''), data.get('password', '')
    now = int(time.time())
    with database() as connection:
        connection.execute('INSERT INTO login_limit VALUES (1, 0, ?) ON CONFLICT(id) DO NOTHING', (now,))
        connection.execute('UPDATE login_limit SET attempts = 0, window_start = ? WHERE id = 1 AND window_start <= ?', (now, now - LOGIN_WINDOW))
        attempts = connection.execute('SELECT attempts FROM login_limit WHERE id = 1').fetchone()[0]
        if attempts >= MAX_ATTEMPTS:
            response = login_page(current['csrf'], 'Te veel inlogpogingen. Probeer het over vijf minuten opnieuw.', 429)
            response.headers['Retry-After'] = str(LOGIN_WINDOW)
            return response
        connection.execute('UPDATE login_limit SET attempts = attempts + 1 WHERE id = 1')
        admin = connection.execute('SELECT * FROM administrator WHERE id = 1').fetchone()
    valid = verify_password(password, admin['password_hash'] if admin else DUMMY_HASH) if len(password) <= 256 else False
    if not admin or not secrets.compare_digest(username.encode(), admin['username'].encode()) or not valid:
        return login_page(current['csrf'], 'Gebruikersnaam of wachtwoord is onjuist.', 401)
    response = RedirectResponse('/ui/customers', status_code=303)
    new_session(response, authenticated=True, old=current)
    return response


@router.post('/logout')
async def logout(request: Request):
    current = session(request)
    csrf_check(current, await form_data(request))
    with database() as connection:
        connection.execute('DELETE FROM web_sessions WHERE token_hash = ?', (current['token_hash'],))
    response = RedirectResponse('/login', status_code=303)
    response.delete_cookie(cookie_name(), path='/', secure=secure_cookie(), httponly=True, samesite='strict')
    return response


@router.get('/ui/customers')
def customers(request: Request, archived: bool = False, offset: int = 0):
    current = require_login(request)
    if not current:
        return RedirectResponse('/login', status_code=303)
    offset = max(0, offset)
    with database() as connection:
        rows = connection.execute('SELECT * FROM customers WHERE (? OR archived = 0) ORDER BY id LIMIT 51 OFFSET ?', (archived, offset)).fetchall()
    cards = ''
    for row in rows[:50]:
        status = 'Gearchiveerd' if row['archived'] else 'Actief'
        cards += f'<tr><td><a href="/ui/customers/{row["id"]}">{escape(row["name"])}</a></td><td>{escape(row["email"])}</td><td><span class="badge">{status}</span></td><td><a href="/ui/customers/{row["id"]}/edit">Wijzigen</a></td></tr>'
    paging = ''
    if offset:
        paging += f'<a href="?archived={str(archived).lower()}&offset={max(0, offset-50)}">← Vorige</a> '
    if len(rows) > 50:
        paging += f'<a href="?archived={str(archived).lower()}&offset={offset+50}">Volgende →</a>'
    return page('Je klanten', f'''<div class="toolbar"><p>Alle klantgegevens op één plek.</p><a class="button" href="/ui/customers/new">+ Klant toevoegen</a></div>
<p><a href="/ui/customers">Actieve klanten</a> · <a href="?archived=true">Inclusief archief</a></p>
<section class="card table"><table><thead><tr><th>Naam</th><th>E-mailadres</th><th>Status</th><th>Actie</th></tr></thead><tbody>{cards}</tbody></table>
{'' if cards else '<p>Nog geen klanten. Voeg je eerste klant toe om te beginnen.</p>'}</section><p>{paging}</p>''', current)


def customer_form(current, values=None, customer_id=None, error='', status=200):
    values = values or {}
    fields = ''
    for key, label, limit in [('name', 'Naam / bedrijfsnaam', 200), ('email', 'E-mailadres', 254), ('address', 'Adres', 2000), ('vat_identifier', 'Btw-nummer (optioneel)', 64)]:
        value = escape(str(values.get(key) or ''), quote=True)
        required = '' if key == 'vat_identifier' else 'required'
        if key == 'address':
            field = f'<textarea name="{key}" maxlength="{limit}" {required}>{value}</textarea>'
        else:
            kind = 'email' if key == 'email' else 'text'
            field = f'<input type="{kind}" name="{key}" value="{value}" maxlength="{limit}" {required}>'
        fields += f'<label>{label}{field}</label>'
    action = f'/ui/customers/{customer_id}/edit' if customer_id else '/ui/customers/new'
    return page('Klant wijzigen' if customer_id else 'Klant toevoegen', f'<section class="card"><p role="alert" class="error">{escape(error)}</p><form method="post" action="{action}">{hidden(current["csrf"])}{fields}<div class="actions"><button>Opslaan</button><a href="/ui/customers">Annuleren</a></div></form></section>', current, status)


@router.get('/ui/customers/new')
def new_customer(request: Request):
    current = require_login(request)
    return customer_form(current) if current else RedirectResponse('/login', status_code=303)


@router.get('/ui/customers/{customer_id}')
def detail(request: Request, customer_id: int):
    current = require_login(request)
    if not current:
        return RedirectResponse('/login', status_code=303)
    with database() as connection:
        row = find(connection, customer_id)
    content = ''.join(f'<dt>{label}</dt><dd>{escape(str(row[key] or "Niet ingevuld"))}</dd>' for key, label in [('email', 'E-mailadres'), ('address', 'Adres'), ('vat_identifier', 'Btw-nummer')])
    archive = '<p class="badge">Gearchiveerd</p>' if row['archived'] else f'<form method="post" action="/ui/customers/{customer_id}/archive">{hidden(current["csrf"])}<p>Archiveren verbergt deze klant in het actieve overzicht. De gegevens blijven bewaard.</p><button class="quiet">Klant archiveren</button></form>'
    return page(row['name'], f'<section class="card"><dl>{content}</dl><a class="button" href="/ui/customers/{customer_id}/edit">Gegevens wijzigen</a>{archive}</section><p><a href="/ui/customers">← Terug naar klanten</a></p>', current)


@router.get('/ui/customers/{customer_id}/edit')
def edit(request: Request, customer_id: int):
    current = require_login(request)
    if not current:
        return RedirectResponse('/login', status_code=303)
    with database() as connection:
        return customer_form(current, find(connection, customer_id), customer_id)


async def save_customer(request, customer_id=None):
    current = require_login(request)
    if not current:
        return RedirectResponse('/login', status_code=303)
    data = await form_data(request)
    csrf_check(current, data)
    try:
        values = CustomerInput.model_validate(data)
    except ValidationError:
        return customer_form(current, data, customer_id, 'Controleer de velden. Vul een naam, geldig e-mailadres en adres in; houd rekening met de maximale lengte.', 422)
    row = update_customer(customer_id, values) if customer_id else create_customer(values)
    return RedirectResponse(f'/ui/customers/{row["id"]}', status_code=303)


@router.post('/ui/customers/new')
async def create(request: Request):
    return await save_customer(request)


@router.post('/ui/customers/{customer_id}/edit')
async def save(request: Request, customer_id: int):
    return await save_customer(request, customer_id)


@router.post('/ui/customers/{customer_id}/archive')
async def archive(request: Request, customer_id: int):
    current = require_login(request)
    if not current:
        return RedirectResponse('/login', status_code=303)
    csrf_check(current, await form_data(request))
    archive_customer(customer_id)
    return RedirectResponse('/ui/customers', status_code=303)


@router.get('/ui/style.css')
def style():
    return Response('''*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#182a40;font:16px/1.6 system-ui,sans-serif}header{background:white;border-bottom:1px solid #dce4ee;padding:20px max(24px,calc((100% - 1080px)/2));display:flex;justify-content:space-between;align-items:center;gap:20px}.brand{font-size:24px;font-weight:800;text-decoration:none;color:#163858}nav,.toolbar,.actions{display:flex;gap:20px;align-items:center;justify-content:space-between}nav form{margin:0}main{max-width:1080px;margin:48px auto;padding:0 24px;min-height:65vh}h1{font-size:clamp(28px,4vw,40px);letter-spacing:-1px;margin:4px 0 20px}.eyebrow{font-size:12px;letter-spacing:2px;color:#52677d;font-weight:700}.card{background:white;border:1px solid #dce4ee;border-radius:16px;padding:28px;margin:24px 0;box-shadow:0 6px 24px #182a4006}.login{max-width:460px}form{max-width:650px}label{display:block;font-weight:600;margin:16px 0}input,textarea{display:block;width:100%;padding:12px;margin-top:6px;border:1px solid #94a3b8;border-radius:8px;font:inherit;color:inherit;background:white}textarea{min-height:120px;resize:vertical}button,.button{display:inline-block;background:#155d56;color:white;padding:11px 20px;border:0;border-radius:8px;font:inherit;font-weight:600;text-decoration:none;cursor:pointer}button:hover,.button:hover{background:#104b45}.quiet{background:#e7eef4;color:#223b53}.quiet:hover{background:#d9e4ed}a{color:#125f63;text-underline-offset:3px}a:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid #d18b21;outline-offset:3px}table{width:100%;border-collapse:collapse;text-align:left}th{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#52677d}th,td{padding:16px 12px;border-bottom:1px solid #edf0f5}.table{overflow:auto}.badge{font-size:13px;background:#e8f4ee;color:#245d46;border-radius:20px;padding:4px 10px;display:inline-block}.error{color:#a62626}dt{font-size:13px;color:#52677d}dd{margin:0 0 20px;white-space:pre-wrap;overflow-wrap:anywhere}footer{max-width:1080px;margin:auto;padding:24px;color:#52677d;font-size:13px}@media(max-width:640px){header{padding:16px}.toolbar{align-items:flex-start;flex-direction:column}.card{padding:18px}main{margin-top:28px}.brand{font-size:20px}nav{gap:12px}th,td{padding:10px}}''', media_type='text/css')
