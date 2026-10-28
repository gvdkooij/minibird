"""Single-operator customer API with transactional SQLite migrations."""
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator


def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False))):
    token = os.environ.get("MINIBIRD_ADMIN_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "Customer access is not configured")
    if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), token.encode()):
        raise HTTPException(401, "Invalid administrator token", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/customers", tags=["customers"], dependencies=[Depends(authorize)])


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=254)
    address: str = Field(min_length=1, max_length=2000)
    vat_identifier: str | None = Field(default=None, max_length=64)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("Invalid email address")
        return value

    @field_validator("name", "email", "address", "vat_identifier")
    @classmethod
    def reject_controls(cls, value):
        if value is not None and any(ord(c) < 32 and c != "\n" for c in value):
            raise ValueError("Control characters are not allowed")
        return value


class Customer(CustomerInput):
    id: int
    archived: bool


# Migrations are append-only. Each version and its changes commit together.
MIGRATIONS = (
    ("""CREATE TABLE customers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        address TEXT NOT NULL,
        vat_identifier TEXT,
        archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
    )""",),
    (
        "CREATE TABLE administrator (id INTEGER PRIMARY KEY CHECK (id = 1), username TEXT NOT NULL, password_hash TEXT NOT NULL)",
        "CREATE TABLE web_sessions (token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, authenticated INTEGER NOT NULL DEFAULT 0, expires INTEGER NOT NULL)",
        "CREATE TABLE login_limit (id INTEGER PRIMARY KEY CHECK (id = 1), attempts INTEGER NOT NULL, window_start INTEGER NOT NULL)",
    ),
)


def migrate(connection):
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
        if versions != list(range(1, len(versions) + 1)) or len(versions) > len(MIGRATIONS):
            raise RuntimeError("Unsupported database schema; restore the matching application version")
        for version, statements in enumerate(MIGRATIONS, 1):
            if version not in versions:
                for statement in statements:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations VALUES (?)", (version,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise


@contextmanager
def database():
    url = os.environ.get("MINIBIRD_DATABASE_URL", "sqlite:///./data/minibird.sqlite3")
    if not url.startswith("sqlite:///") or url == "sqlite:///:memory:":
        raise RuntimeError("MINIBIRD_DATABASE_URL must name a persistent SQLite file")
    path = Path(url[len("sqlite:///"):])
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        migrate(connection)
        with connection:
            yield connection
    finally:
        connection.close()


def find(connection, customer_id):
    row = connection.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Customer not found")
    return dict(row)


@router.post("", response_model=Customer, status_code=201)
def create_customer(customer: CustomerInput):
    with database() as connection:
        cursor = connection.execute(
            "INSERT INTO customers (name, email, address, vat_identifier) VALUES (?, ?, ?, ?)",
            (customer.name, customer.email, customer.address, customer.vat_identifier),
        )
        return find(connection, cursor.lastrowid)


@router.get("", response_model=list[Customer])
def list_customers(include_archived: bool = False, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    with database() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM customers WHERE (? OR archived = 0) ORDER BY id LIMIT ? OFFSET ?",
            (include_archived, limit, offset),
        )]


@router.get("/{customer_id}", response_model=Customer)
def get_customer(customer_id: int):
    with database() as connection:
        return find(connection, customer_id)


@router.put("/{customer_id}", response_model=Customer)
def update_customer(customer_id: int, customer: CustomerInput):
    with database() as connection:
        find(connection, customer_id)
        connection.execute(
            "UPDATE customers SET name = ?, email = ?, address = ?, vat_identifier = ? WHERE id = ?",
            (customer.name, customer.email, customer.address, customer.vat_identifier, customer_id),
        )
        return find(connection, customer_id)


@router.post("/{customer_id}/archive", response_model=Customer)
def archive_customer(customer_id: int):
    with database() as connection:
        find(connection, customer_id)
        connection.execute("UPDATE customers SET archived = 1 WHERE id = ?", (customer_id,))
        return find(connection, customer_id)
