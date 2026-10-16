"""Workflow 1 through the API: the stored procedure, the audit trigger and the partial unique index.
Each test uses its own throw-away user (conftest.make_user), so the demo fixtures are never touched."""
import pytest

import db


def checkout(client, user_id, restaurant_id, amount):
    return client.post("/api/checkout", json={"user_id": user_id, "restaurant_id": restaurant_id, "amount": amount})


def balance(user_id):
    return float(db.one("SELECT wallet_balance FROM users WHERE id = %s", [user_id])["wallet_balance"])


def active_orders(user_id):
    return db.one(
        "SELECT COUNT(*) AS n FROM orders WHERE user_id = %s AND status IN ('PREPARING', 'DELIVERING')", [user_id]
    )["n"]


def test_checkout_success_debits_wallet_and_writes_audit_row(client, restaurant_id, make_user):
    user = make_user(1000)
    res = checkout(client, user, restaurant_id, 250)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["order"]["status"] == "PREPARING"
    assert float(body["order"]["total_amount"]) == pytest.approx(250)
    assert float(body["balance_before"]) == pytest.approx(1000)
    assert float(body["balance_after"]) == pytest.approx(750)
    audit = body["audit_entry"]  # written by the wallet trigger inside the procedure's transaction
    assert audit["action_type"] == "DEBIT"
    assert float(audit["amount_changed"]) == pytest.approx(250)
    assert float(audit["balance_after"]) == pytest.approx(750)
    assert balance(user) == pytest.approx(750)


def test_insufficient_balance_is_rejected_and_rolled_back(client, restaurant_id, make_user):
    user = make_user(50)
    res = checkout(client, user, restaurant_id, 100)
    assert res.status_code == 409
    assert res.json()["error_code"] == "INSUFFICIENT_BALANCE"
    assert res.json()["sqlstate"] == "P0001"
    assert balance(user) == pytest.approx(50)  # nothing debited
    assert active_orders(user) == 0  # no order created
    assert db.one("SELECT COUNT(*) AS n FROM wallet_audit_logs WHERE user_id = %s", [user])["n"] == 0


def test_second_active_order_is_blocked_until_the_first_is_delivered(client, restaurant_id, make_user):
    user = make_user(1000)
    first = checkout(client, user, restaurant_id, 100)
    assert first.status_code == 200, first.text

    second = checkout(client, user, restaurant_id, 100)
    assert second.status_code == 409
    assert second.json()["error_code"] == "ACTIVE_ORDER_EXISTS"
    assert second.json()["sqlstate"] == "23505"
    assert balance(user) == pytest.approx(900)  # the failed checkout debited nothing

    order_id = first.json()["order"]["id"]
    assert client.post(f"/api/orders/{order_id}/advance").json()["status"] == "DELIVERING"
    assert client.post(f"/api/orders/{order_id}/advance").json()["status"] == "DELIVERED"
    assert client.post(f"/api/orders/{order_id}/advance").status_code == 409  # already delivered

    third = checkout(client, user, restaurant_id, 100)
    assert third.status_code == 200, third.text
    assert balance(user) == pytest.approx(800)


@pytest.mark.parametrize("amount, status, code", [
    (0, 400, "INVALID_AMOUNT"),             # reaches the procedure: SQLSTATE 22023
    (-5, 400, "INVALID_AMOUNT"),
    (99999999999, 400, "AMOUNT_TOO_LARGE"),  # rejected by the API before the database
])
def test_invalid_amounts(client, restaurant_id, make_user, amount, status, code):
    user = make_user(1000)
    res = checkout(client, user, restaurant_id, amount)
    assert res.status_code == status
    assert res.json()["error_code"] == code
    assert balance(user) == pytest.approx(1000)


def test_unknown_restaurant_and_user(client, restaurant_id, make_user):
    user = make_user(1000)
    unknown = "00000000-0000-4000-8000-0000000000ff"
    assert checkout(client, user, unknown, 10).status_code == 404
    assert checkout(client, unknown, restaurant_id, 10).status_code == 404


def test_topup_writes_credit_and_rejects_balance_overflow(client, make_user):
    user = make_user(100)
    res = client.post(f"/api/users/{user}/topup", json={"amount": 400})
    assert res.status_code == 200, res.text
    assert res.json()["audit_entry"]["action_type"] == "CREDIT"
    assert balance(user) == pytest.approx(500)

    rich = make_user(99999999)
    over = client.post(f"/api/users/{rich}/topup", json={"amount": 100})  # amount fits, new balance doesn't
    assert over.status_code == 400
    assert over.json()["error_code"] == "AMOUNT_TOO_LARGE"
    assert balance(rich) == pytest.approx(99999999)
