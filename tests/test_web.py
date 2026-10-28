import re
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from minibird.admin import hash_password, set_administrator, verify_password
from minibird.customers import database
from minibird.main import app
from minibird.web import cookie_name, LOGIN_WINDOW

PASSWORD = 'Fictional-test-password-123'
CUSTOMER = {'name': 'Voorbeeldbedrijf', 'email': 'klant@example.test', 'address': 'Fictieve straat 1', 'vat_identifier': 'TEST123'}


def csrf(response):
    return re.search(r'name="csrf" value="([a-f0-9]+)"', response.text)[1]


@pytest.fixture
def browser(tmp_path, monkeypatch):
    monkeypatch.setenv('MINIBIRD_DATABASE_URL', f'sqlite:///{tmp_path / "web.sqlite3"}')
    monkeypatch.delenv('MINIBIRD_DEV_HTTP', raising=False)
    monkeypatch.delenv('MINIBIRD_ADMIN_TOKEN', raising=False)
    set_administrator('beheerder', PASSWORD)
    with TestClient(app, base_url='https://testserver', follow_redirects=False) as client:
        yield client


def login(browser, password=PASSWORD, username='beheerder'):
    token = csrf(browser.get('/login'))
    return browser.post('/login', data={'csrf': token, 'username': username, 'password': password})


def test_password_hash_and_reset(browser):
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second
    assert PASSWORD not in first
    assert verify_password(PASSWORD, first)
    assert not verify_password('wrong', first)
    assert not verify_password(PASSWORD, 'malformed')
    login(browser)
    set_administrator('nieuw', 'Another-fictional-password')
    assert browser.get('/ui/customers').status_code == 303
    assert login(browser).status_code == 401
    assert login(browser, 'Another-fictional-password', 'nieuw').status_code == 303
    with database() as connection:
        row = connection.execute('SELECT * FROM administrator').fetchone()
        assert row['username'] == 'nieuw'
        assert 'Another-fictional-password' not in row['password_hash']


@pytest.mark.parametrize('username,password', [('', PASSWORD), ('x' * 101, PASSWORD), ('beheerder', 'short')])
def test_account_validation(browser, username, password):
    with pytest.raises(ValueError):
        set_administrator(username, password)


def test_cookie_security_rotation_and_logout(browser):
    page = browser.get('/login')
    old = browser.cookies.get(cookie_name())
    response = browser.post('/login', data={'csrf': csrf(page), 'username': 'beheerder', 'password': PASSWORD})
    assert response.status_code == 303
    cookie = response.headers['set-cookie']
    for flag in ['HttpOnly', 'Secure', 'SameSite=strict', 'Path=/', 'Max-Age=28800', '__Host-minibird=']:
        assert flag in cookie
    assert 'Domain=' not in cookie
    token = browser.cookies.get(cookie_name())
    assert token != old
    with database() as connection:
        assert connection.execute('SELECT token_hash FROM web_sessions WHERE authenticated=1').fetchone()[0] != token
    assert browser.get('/ui/customers', headers={'Cookie': f'{cookie_name()}={old}'}).status_code == 303
    page = browser.get('/ui/customers')
    assert page.status_code == 200
    assert browser.post('/logout', data={'csrf': csrf(page)}).status_code == 303
    assert browser.get('/ui/customers').status_code == 303
    assert browser.get('/ui/customers', headers={'Cookie': f'{cookie_name()}={token}'}).status_code == 303


@pytest.mark.parametrize('path', ['/ui/customers', '/ui/customers/new', '/ui/customers/1', '/ui/customers/1/edit'])
def test_anonymous_customer_pages(browser, path):
    response = browser.get(path)
    assert response.status_code == 303
    assert response.headers['location'] == '/login'


@pytest.mark.parametrize('path', ['/ui/customers/new', '/ui/customers/1/edit', '/ui/customers/1/archive'])
def test_anonymous_cannot_mutate(browser, path):
    assert browser.post(path, data=CUSTOMER).status_code == 303
    with database() as connection:
        assert connection.execute('SELECT count(*) FROM customers').fetchone()[0] == 0


def test_expired_session(browser, monkeypatch):
    login(browser)
    with database() as connection:
        connection.execute('UPDATE web_sessions SET expires=?', (int(time.time()) - 1,))
    assert browser.get('/ui/customers').status_code == 303
    assert browser.post('/ui/customers/new', data=CUSTOMER).status_code == 303


def test_tampered_session(browser):
    login(browser)
    browser.cookies.clear()
    browser.cookies.set(cookie_name(), 'a' * 64)
    assert browser.get('/ui/customers').status_code == 303


def test_csrf_login_and_customer_operations(browser):
    assert browser.post('/login', data={'username': 'beheerder', 'password': PASSWORD}).status_code == 403
    login(browser)
    for path in ['/ui/customers/new', '/ui/customers/1/edit', '/ui/customers/1/archive', '/logout']:
        for supplied in ['', 'invalid']:
            assert browser.post(path, data=dict(CUSTOMER, csrf=supplied)).status_code == 403
    with TestClient(app, base_url='https://testserver') as other:
        other_csrf = csrf(other.get('/login'))
    assert browser.post('/ui/customers/new', data=dict(CUSTOMER, csrf=other_csrf)).status_code == 403
    with database() as connection:
        assert connection.execute('SELECT count(*) FROM customers').fetchone()[0] == 0


def test_rate_limit_persists_and_expires(browser):
    for attempt in range(5):
        response = login(browser, 'wrong', 'unknown' if attempt % 2 else 'beheerder')
        assert response.status_code == 401
        assert 'Gebruikersnaam of wachtwoord is onjuist.' in response.text
    # A new browser and even the correct password cannot bypass the shared limit.
    with TestClient(app, base_url='https://testserver', follow_redirects=False) as other:
        response = login(other)
        assert response.status_code == 429
        assert response.headers['retry-after'] == '300'
    with database() as connection:
        connection.execute('UPDATE login_limit SET window_start=?', (int(time.time()) - LOGIN_WINDOW,))
    assert login(browser).status_code == 303


def test_customer_browser_workflow_and_api_independence(browser, monkeypatch):
    login(browser)
    page = browser.get('/ui/customers/new')
    assert 'Klant toevoegen' in page.text
    token = csrf(page)
    assert browser.post('/ui/customers/new', data=dict(CUSTOMER, csrf=token)).status_code == 303
    page = browser.get('/ui/customers')
    assert 'Voorbeeldbedrijf' in page.text
    assert 'Voorbeeldbedrijf' in browser.get('/ui/customers/1').text
    assert 'TEST123' in browser.get('/ui/customers/1/edit').text
    assert browser.post('/ui/customers/1/edit', data=dict(CUSTOMER, name='Gewijzigd', csrf=token)).status_code == 303
    assert 'Gewijzigd' in browser.get('/ui/customers/1').text
    monkeypatch.setenv('MINIBIRD_ADMIN_TOKEN', 'api-test-' + 'x' * 40)
    # A browser cookie never authorizes the bearer API.
    assert browser.get('/customers').status_code == 401
    response = browser.get('/customers', headers={'Authorization': 'Bearer api-test-' + 'x' * 40})
    assert response.json()[0]['name'] == 'Gewijzigd'
    for _ in range(2):
        assert browser.post('/ui/customers/1/archive', data={'csrf': token}).status_code == 303
    assert 'Gewijzigd' not in browser.get('/ui/customers').text
    assert 'Gewijzigd' in browser.get('/ui/customers?archived=true').text
    assert 'Gearchiveerd' in browser.get('/ui/customers/1').text
    # Credentials survive a process/client restart.
    with TestClient(app, base_url='https://testserver', follow_redirects=False) as restarted:
        assert login(restarted).status_code == 303
        assert 'Gewijzigd' in restarted.get('/ui/customers?archived=true').text


def test_browser_validation_and_escaping(browser):
    login(browser)
    token = csrf(browser.get('/ui/customers/new'))
    invalid = dict(CUSTOMER, email='not-an-email', name='<script>alert(1)</script>', csrf=token)
    response = browser.post('/ui/customers/new', data=invalid)
    assert response.status_code == 422
    assert '<script>' not in response.text
    assert '&lt;script&gt;' in response.text
    with database() as connection:
        assert connection.execute('SELECT count(*) FROM customers').fetchone()[0] == 0
    valid = dict(CUSTOMER, name='<script>alert(1)</script>', csrf=token)
    browser.post('/ui/customers/new', data=valid)
    for path in ['/ui/customers', '/ui/customers/1', '/ui/customers/1/edit']:
        response = browser.get(path)
        assert '<script>' not in response.text
        assert '&lt;script&gt;' in response.text
    assert browser.post('/ui/customers/1/edit', data=dict(CUSTOMER, email='bad', csrf=token)).status_code == 422
    assert '&lt;script&gt;' in browser.get('/ui/customers/1').text


def test_request_limits_and_headers(browser):
    login(browser)
    response = browser.get('/ui/customers/new')
    token = csrf(response)
    assert response.headers['cache-control'] == 'no-store'
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert browser.post('/ui/customers/new', json=CUSTOMER).status_code == 415
    assert browser.post('/ui/customers/new', content='name=' + 'x' * 17000, headers={'Content-Type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert browser.post('/ui/customers/new', content=f'csrf={token}&name=a&name=b', headers={'Content-Type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert browser.get('/ui/customers/999').status_code == 404
    assert browser.get('/ui/style.css').status_code == 200
    assert browser.get('/', headers={'Accept': 'text/html'}).headers['location'] == '/ui/customers'


def test_upgrade_from_customer_only_schema(browser, tmp_path):
    from minibird.customers import MIGRATIONS, migrate
    path = tmp_path / 'old.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)')
        connection.execute(MIGRATIONS[0][0])
        connection.execute('INSERT INTO schema_migrations VALUES (1)')
        connection.execute("INSERT INTO customers VALUES (1, 'Fictieve klant', 'old@example.test', 'Testadres', NULL, 1)")
        connection.commit()
        migrate(connection)
        assert connection.execute('SELECT name, archived FROM customers').fetchone() == ('Fictieve klant', 1)
        assert connection.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall() == [(1,), (2,)]
        migrate(connection)
        assert connection.execute('SELECT count(*) FROM customers').fetchone()[0] == 1


def test_local_http_is_explicit(browser, monkeypatch):
    monkeypatch.setenv('MINIBIRD_DEV_HTTP', '1')
    with TestClient(app, base_url='http://testserver', follow_redirects=False) as local:
        assert login(local).status_code == 303
        assert local.get('/ui/customers').status_code == 200
        assert 'minibird-dev=' in local.get('/login').request.headers['cookie']


def test_unconfigured_account_stays_closed(browser):
    with database() as connection:
        connection.execute('DELETE FROM administrator')
    assert login(browser).status_code == 401
    assert browser.get('/ui/customers').status_code == 303


def test_bearer_token_does_not_authorize_browser(browser, monkeypatch):
    monkeypatch.setenv('MINIBIRD_ADMIN_TOKEN', 'x' * 40)
    assert browser.get('/ui/customers', headers={'Authorization': 'Bearer ' + 'x' * 40}).status_code == 303


def test_admin_command_prompts_without_echoing_password(browser, monkeypatch, capsys):
    from minibird.admin import main
    monkeypatch.setattr('builtins.input', lambda prompt: 'cli-beheerder')
    monkeypatch.setattr('getpass.getpass', lambda prompt: PASSWORD)
    main()
    output = capsys.readouterr().out
    assert PASSWORD not in output
    assert 'opgeslagen' in output
    assert login(browser, username='cli-beheerder').status_code == 303
