"""Materialized-view refresh log, audit-trail time zones and the Workflow 3 map endpoint."""
from datetime import datetime

import db


def test_refresh_updates_both_views_and_is_logged(client):
    before = db.one("SELECT COUNT(*) AS n FROM mv_refresh_log")["n"]
    res = client.post("/api/analytics/refresh")
    assert res.status_code == 200, res.text
    refreshed = res.json()["last_refreshed"]
    assert refreshed

    rows = db.all("SELECT view_name FROM mv_refresh_log ORDER BY id DESC LIMIT 2")
    assert {r["view_name"] for r in rows} == {"mv_restaurant_revenue_summary", "mv_restaurant_daily_revenue"}
    assert db.one("SELECT COUNT(*) AS n FROM mv_refresh_log")["n"] == before + 2

    summary = client.get("/api/analytics/summary").json()
    assert summary["populated"] is True
    assert datetime.fromisoformat(summary["last_refreshed"]) == datetime.fromisoformat(refreshed)


def test_audit_date_filter_uses_the_callers_time_zone_or_ist(client, make_user):
    user = make_user(100)
    for tz, expected in [("Asia/Kolkata", "Asia/Kolkata"), ("America/New_York", "America/New_York"),
                         ("Not/AZone", "Asia/Kolkata"), ("../../etc/passwd", "Asia/Kolkata"), (None, "Asia/Kolkata")]:
        params = {"from": "2026-10-01", "to": "2026-10-31"}
        if tz is not None:
            params["tz"] = tz
        res = client.get(f"/api/users/{user}/audit", params=params)
        assert res.status_code == 200, res.text
        assert res.json()["timezone"] == expected


def test_nearby_drivers_are_distinct_active_and_sorted(client, restaurant_id):
    res = client.get("/api/drivers/nearby", params={"restaurant_id": restaurant_id, "fresh_minutes": 240})
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    distances = [d["distance_m"] for d in items]
    assert distances == sorted(distances)
    assert all(d <= 5000 for d in distances)
    assert all(d["active"] for d in items)
    assert len({d["driver_id"] for d in items}) == len(items)  # one row per driver
