import sqlite3

import pytest
from fastapi.testclient import TestClient

from minibird.main import app
from minibird.customers import migrate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIBIRD_DATABASE_URL", f"sqlite:///{tmp_path / 'test.sqlite3'}")
    monkeypatch.setenv("MINIBIRD_ADMIN_TOKEN", "test-only-token-" + "x" * 32)
    with TestClient(app, headers={"Authorization": "Bearer test-only-token-" + "x" * 32}) as client:
        yield client


@pytest.fixture
def customer():
    return {"name": "Example Test Company", "email": "customer@example.test", "address": "1 Fictional Street", "vat_identifier": "TEST123"}


def test_customer_lifecycle(client, customer):
    response = client.post('/customers', json=customer)
    assert response.status_code == 201
    record = response.json()
    assert record == dict(customer, id=1, archived=False)
    assert client.get('/customers').json() == [record]
    assert client.get('/customers/1').json() == record
    changed = dict(customer, name='Updated Example', vat_identifier=None)
    response = client.put('/customers/1', json=changed)
    assert response.status_code == 200
    assert response.json() == dict(changed, id=1, archived=False)
    for _ in range(2):
        assert client.post('/customers/1/archive').json()['archived'] is True
    assert client.get('/customers').json() == []
    assert len(client.get('/customers?include_archived=true').json()) == 1
    assert client.get('/customers/1').json()['name'] == 'Updated Example'
    assert client.put('/customers/1', json=customer).json()['archived'] is True


@pytest.mark.parametrize('changes', [
    {'name': ''}, {'name': '  '}, {'name': 'x' * 201}, {'email': 'invalid'},
    {'email': 'a@b'}, {'email': 'a b@example.test'}, {'address': ''},
    {'address': 'x' * 2001}, {'vat_identifier': 'x' * 65}, {'archived': True},
    {'id': 5}, {'name': 'bad\x00name'}, {'email': None},
])
def test_validation(client, customer, changes):
    invalid = dict(customer, **changes)
    assert client.post('/customers', json=invalid).status_code == 422
    assert client.get('/customers').json() == []
    client.post('/customers', json=customer)
    assert client.put('/customers/1', json=invalid).status_code == 422
    assert client.get('/customers/1').json()['name'] == customer['name']


@pytest.mark.parametrize('method,path', [('get', '/customers'), ('get', '/customers/1'), ('post', '/customers'), ('put', '/customers/1'), ('post', '/customers/1/archive')])
def test_authentication(client, customer, method, path, monkeypatch):
    for token in ['', 'Bearer wrong', 'Basic wrong']:
        headers = {'Authorization': token}
        assert client.request(method, path, headers=headers, json=customer).status_code == 401
    monkeypatch.delenv('MINIBIRD_ADMIN_TOKEN')
    assert client.request(method, path, json=customer).status_code == 503


def test_missing_customers(client, customer):
    assert client.get('/customers/99').status_code == 404
    assert client.put('/customers/99', json=customer).status_code == 404
    assert client.post('/customers/99/archive').status_code == 404


def test_persistence_and_repeatable_upgrade(client, customer, tmp_path):
    client.post('/customers', json=customer)
    path = tmp_path / 'test.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE unrelated (value TEXT)')
        connection.execute("INSERT INTO unrelated VALUES ('preserve me')")
    for _ in range(2):
        with sqlite3.connect(path) as connection:
            migrate(connection)
            assert connection.execute('SELECT value FROM unrelated').fetchone()[0] == 'preserve me'
            assert connection.execute('SELECT name FROM customers').fetchone()[0] == customer['name']
            assert connection.execute('SELECT version FROM schema_migrations').fetchall() == [(1,)]
    with TestClient(app, headers=client.headers) as restarted:
        assert restarted.get('/customers/1').json()['email'] == customer['email']


def test_reject_newer_schema_without_changing_data(tmp_path):
    with sqlite3.connect(tmp_path / 'newer.sqlite3') as connection:
        connection.execute('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)')
        connection.executemany('INSERT INTO schema_migrations VALUES (?)', [(1,), (2,)])
        connection.commit()
        with pytest.raises(RuntimeError, match='Unsupported'):
            migrate(connection)
        assert connection.execute('SELECT version FROM schema_migrations').fetchall() == [(1,), (2,)]


def test_optional_vat_pagination_and_sql_input(client, customer):
    customer.pop('vat_identifier')
    customer['name'] = "Example'); DROP TABLE customers; --"
    assert client.post('/customers', json=customer).json()['vat_identifier'] is None
    client.post('/customers', json=dict(customer, name='Second'))
    assert client.get('/customers?limit=1&offset=1').json()[0]['name'] == 'Second'
    for query in ['limit=0', 'limit=501', 'offset=-1']:
        assert client.get('/customers?' + query).status_code == 422
