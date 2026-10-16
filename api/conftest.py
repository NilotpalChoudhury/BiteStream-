"""Integration tests: they need the seeded Postgres (and Mongo for the map test).
Tests create their own throw-away users, so they never depend on seed fixtures.
(wallet_audit_logs is insert-only, so the test users/audit rows are left behind - harmless.)"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import db
from main import app


@pytest.fixture(scope="session")
def client():
    try:
        with TestClient(app) as c:
            db.one("SELECT 1")
            yield c
    except Exception as exc:  # DB not reachable -> skip instead of failing
        pytest.skip(f"Database not available: {exc}")


@pytest.fixture()
def restaurant_id():
    row = db.one("SELECT id FROM restaurants ORDER BY id LIMIT 1")
    assert row, "no restaurants - seed the database first"
    return str(row["id"])


@pytest.fixture()
def make_user():
    def _make(balance):
        uid = uuid4()
        db.run("INSERT INTO users (id, name, wallet_balance) VALUES (%s, %s, %s)", [uid, f"test_{uid.hex[:8]}", balance])
        return str(uid)
    return _make
