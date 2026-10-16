"""BiteStream API - thin layer over the PostgreSQL + MongoDB objects from Assignment 1.

Rule: the database does the real work (stored procedure, trigger, materialized view,
window query, $geoNear, $facet). Handlers here only call those and shape the JSON.
Run:  uvicorn main:app --reload --port 8000     (from the api/ folder)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import db
from errors import ApiError, map_pg_error

log = logging.getLogger("bitestream")

SQL_DIR = Path(os.getenv("SQL_DIR", Path(__file__).resolve().parent.parent / "sql"))
DRIVER_FRESH_MINUTES = int(os.getenv("DRIVER_FRESH_MINUTES", "30"))
NEXT_STATUS = {"PREPARING": "DELIVERING", "DELIVERING": "DELIVERED"}
ORDER_STATUSES = {"PREPARING", "DELIVERING", "DELIVERED"}
_last_refresh_memory: dict = {"at": None}  # fallback if mv_refresh_log does not exist
SUMMARY_VIEW = "mv_restaurant_daily_revenue"  # the view /analytics/summary reads
MAX_AMOUNT = Decimal("99999999.99")  # DECIMAL(10,2): largest order / wallet balance
DEFAULT_TZ = "Asia/Kolkata"  # fallback for the audit date filter


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.pool.open()
    yield
    db.pool.close()
    db.mongo_client.close()


app = FastAPI(title="BiteStream API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------- error handling
def _err(status, code, message, sqlstate=None):
    body = {"error_code": code, "message": message}
    if sqlstate:
        body["sqlstate"] = sqlstate
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return _err(exc.status, exc.error_code, exc.message, exc.sqlstate)


@app.exception_handler(psycopg.Error)
async def pg_error_handler(_: Request, exc: psycopg.Error):
    e = map_pg_error(exc)
    if e.status >= 500:
        log.exception("Unhandled database error")
    return _err(e.status, e.error_code, e.message, e.sqlstate)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return _err(400, "VALIDATION_ERROR", f"Invalid input for '{where}': {first.get('msg', 'bad value')}")


@app.exception_handler(Exception)
async def fallback_handler(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return _err(500, "SERVER_ERROR", "Unexpected server error.")


# ----------------------------------------------------------------------- helpers
def _like(q: str) -> str:
    """Escape % and _ so user text is searched literally."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _paged(items, total, page, limit):
    return {"items": items, "total": total, "page": page, "limit": limit}


def _mongo_keys(pg_id: UUID, override: Optional[str]):
    """Keys that may identify this restaurant in Mongo.
    Normal case: the Postgres UUID string (after the cross-DB fix). While the inherited
    int ids (1..100) still exist, the frontend/demo can pass ?mongo_key=<int>."""
    keys: list = [str(pg_id)]
    if override:
        keys.append(int(override) if override.isdigit() else override)
    return keys


def _restaurant_or_404(restaurant_id: UUID):
    r = db.one("SELECT id, name, latitude, longitude FROM restaurants WHERE id = %s", [restaurant_id])
    if r is None:
        raise ApiError(404, "RESTAURANT_NOT_FOUND", "Restaurant not found.")
    return r


def _find_menu(restaurant: dict, mongo_key: Optional[str]):
    keys = _mongo_keys(restaurant["id"], mongo_key)
    doc = db.mongo["Menus"].find_one({"restaurant_id": {"$in": keys}})
    if doc is None:  # fallback: match by name
        doc = db.mongo["Menus"].find_one({"restaurant_name": restaurant["name"]})
    if doc is not None:
        doc["_id"] = str(doc["_id"])
    return doc


def _last_refreshed(view: str = SUMMARY_VIEW):
    """Latest refresh of a materialized view, from mv_refresh_log (sql/05_materialized_views.sql).
    Falls back to the time this API process last refreshed, for databases without the log table."""
    try:
        row = db.one("SELECT MAX(refreshed_at) AS t FROM mv_refresh_log WHERE view_name = %s", [view])
        if row and row["t"]:
            return row["t"]
    except psycopg.Error:
        pass
    return _last_refresh_memory["at"]


def _check_amount(amount: Decimal):
    """Reject amounts that cannot fit DECIMAL(10,2) before they reach the database."""
    if amount > MAX_AMOUNT:
        raise ApiError(400, "AMOUNT_TOO_LARGE", "The amount is too large. The maximum is ₹9,99,99,999.99.")


def _resolve_tz(name: Optional[str]):
    """The caller's time zone (IANA name, e.g. 'Asia/Kolkata'); IST if missing or invalid."""
    for candidate in (name, DEFAULT_TZ):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate), candidate
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return timezone(timedelta(hours=5, minutes=30), "IST"), "IST"  # no tz database available


def _window_sql() -> str:
    """Load Workflow 2 query from sql/06_window_analytics.sql so the DB file stays the source of truth."""
    path = SQL_DIR / "06_window_analytics.sql"
    if not path.exists():
        raise ApiError(500, "SQL_FILE_MISSING", f"Cannot find {path}. Set SQL_DIR.")
    text = path.read_text(encoding="utf-8").strip().rstrip(";").strip()
    return text.replace("%", "%%")  # psycopg treats % as a placeholder


# --------------------------------------------------------------------------- health
@app.get("/api/health")
def health():
    pg = mongo_ok = False
    try:
        pg = db.one("SELECT 1 AS ok")["ok"] == 1
    except Exception:
        pass
    try:
        db.mongo_client.admin.command("ping")
        mongo_ok = True
    except Exception:
        pass
    return {"status": "ok" if pg and mongo_ok else "degraded", "postgres": pg, "mongo": mongo_ok}


# --------------------------------------------------------------------------- browse
@app.get("/api/users")
def list_users(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), q: Optional[str] = None):
    where, params = "", []
    if q:
        where, params = "WHERE name ILIKE %s", [_like(q)]
    total = db.one(f"SELECT COUNT(*) AS n FROM users {where}", params)["n"]
    items = db.all(
        f"SELECT id, name, wallet_balance FROM users {where} ORDER BY name, id LIMIT %s OFFSET %s",
        params + [limit, (page - 1) * limit],
    )
    return _paged(items, total, page, limit)


@app.get("/api/users/{user_id}")
def get_user(user_id: UUID):
    user = db.one("SELECT id, name, wallet_balance FROM users WHERE id = %s", [user_id])
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "User not found.")
    user["recent_orders"] = db.all(
        """SELECT o.id, o.restaurant_id, r.name AS restaurant_name, o.total_amount, o.status, o.created_at
           FROM orders o JOIN restaurants r ON r.id = o.restaurant_id
           WHERE o.user_id = %s ORDER BY o.created_at DESC LIMIT 10""",
        [user_id],
    )
    return user


class TopUp(BaseModel):
    amount: Decimal


@app.post("/api/users/{user_id}/topup")
def topup(user_id: UUID, body: TopUp):
    """Demo helper: add money so a user can recover from 'insufficient balance'.
    The UPDATE fires the audit trigger, which writes a CREDIT row."""
    amount = body.amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
    if amount <= 0:
        raise ApiError(400, "INVALID_AMOUNT", "Top-up amount must be greater than zero.")
    _check_amount(amount)
    with db.pool.connection() as conn:
        row = conn.execute(
            "UPDATE users SET wallet_balance = wallet_balance + %s WHERE id = %s RETURNING id, name, wallet_balance",
            [amount, user_id],
        ).fetchone()
        if row is None:
            raise ApiError(404, "USER_NOT_FOUND", "User not found.")
        audit = conn.execute(
            'SELECT * FROM wallet_audit_logs WHERE user_id = %s ORDER BY "timestamp" DESC, id DESC LIMIT 1',
            [user_id],
        ).fetchone()
    return {"user": row, "audit_entry": audit}


@app.get("/api/restaurants")
def list_restaurants(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), q: Optional[str] = None):
    where, params = "", []
    if q:
        where, params = "WHERE name ILIKE %s", [_like(q)]
    total = db.one(f"SELECT COUNT(*) AS n FROM restaurants {where}", params)["n"]
    items = db.all(
        f"SELECT id, name, latitude, longitude FROM restaurants {where} ORDER BY name, id LIMIT %s OFFSET %s",
        params + [limit, (page - 1) * limit],
    )
    return _paged(items, total, page, limit)


@app.get("/api/restaurants/{restaurant_id}")
def get_restaurant(restaurant_id: UUID, mongo_key: Optional[str] = None):
    r = _restaurant_or_404(restaurant_id)
    r["menu"] = _find_menu(r, mongo_key)
    r["menu_found"] = r["menu"] is not None
    return r


@app.get("/api/restaurants/{restaurant_id}/menu")
def get_menu(restaurant_id: UUID, mongo_key: Optional[str] = None):
    r = _restaurant_or_404(restaurant_id)
    menu = _find_menu(r, mongo_key)
    if menu is None:
        raise ApiError(404, "MENU_NOT_FOUND", "No menu is stored for this restaurant.")
    return menu


@app.get("/api/orders")
def list_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    user_id: Optional[UUID] = None,
    restaurant_id: Optional[UUID] = None,
):
    clauses, params = [], []
    if status:
        if status.upper() not in ORDER_STATUSES:
            raise ApiError(400, "VALIDATION_ERROR", f"status must be one of {sorted(ORDER_STATUSES)}")
        clauses.append("o.status = %s")
        params.append(status.upper())
    if user_id:
        clauses.append("o.user_id = %s")
        params.append(user_id)
    if restaurant_id:
        clauses.append("o.restaurant_id = %s")
        params.append(restaurant_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = db.one(f"SELECT COUNT(*) AS n FROM orders o {where}", params)["n"]
    items = db.all(
        f"""SELECT o.id, o.user_id, u.name AS user_name, o.restaurant_id, r.name AS restaurant_name,
                   o.total_amount, o.status, o.created_at
            FROM orders o
            JOIN users u ON u.id = o.user_id
            JOIN restaurants r ON r.id = o.restaurant_id
            {where}
            ORDER BY o.created_at DESC, o.id LIMIT %s OFFSET %s""",
        params + [limit, (page - 1) * limit],
    )
    return _paged(items, total, page, limit)


_ORDER_DETAIL = """SELECT o.id, o.user_id, u.name AS user_name, o.restaurant_id, r.name AS restaurant_name,
                          o.total_amount, o.status, o.created_at
                   FROM orders o JOIN users u ON u.id = o.user_id
                   JOIN restaurants r ON r.id = o.restaurant_id WHERE o.id = %s"""


@app.get("/api/orders/{order_id}")
def get_order(order_id: UUID):
    o = db.one(_ORDER_DETAIL, [order_id])
    if o is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order not found.")
    return o


@app.post("/api/orders/{order_id}/advance")
def advance_order(order_id: UUID):
    """PREPARING -> DELIVERING -> DELIVERED. Lets the demo free a user's active-order slot."""
    with db.pool.connection() as conn:
        row = conn.execute("SELECT status FROM orders WHERE id = %s FOR UPDATE", [order_id]).fetchone()
        if row is None:
            raise ApiError(404, "ORDER_NOT_FOUND", "Order not found.")
        nxt = NEXT_STATUS.get(row["status"])
        if nxt is None:
            raise ApiError(409, "ALREADY_DELIVERED", "This order is already delivered.")
        conn.execute("UPDATE orders SET status = %s WHERE id = %s", [nxt, order_id])
        return conn.execute(_ORDER_DETAIL, [order_id]).fetchone()


# ------------------------------------------------------------- Workflow 1: checkout
class CheckoutRequest(BaseModel):
    user_id: UUID
    restaurant_id: UUID
    amount: Decimal


_RETRY_STATES = ("40001", "40P01")


def _checkout_once(conn, user_id, restaurant_id, amount):
    # sp_execute_checkout runs its own REPEATABLE READ transaction (COMMIT / ROLLBACK inside),
    # so it must be CALLed in autocommit mode, not inside BEGIN ... COMMIT (that raises 2D000).
    if conn.execute("SELECT 1 FROM users WHERE id = %s", [user_id]).fetchone() is None:
        raise ApiError(404, "USER_NOT_FOUND", "User not found.")
    order_id = conn.execute(
        "CALL sp_execute_checkout(%s, %s, %s)", [user_id, restaurant_id, amount]
    ).fetchone()["p_order_id"]
    order = conn.execute(
        "SELECT id, user_id, restaurant_id, total_amount, status, created_at FROM orders WHERE id = %s",
        [order_id],
    ).fetchone()
    # The DEBIT row written by the wallet trigger inside the procedure's transaction.
    audit = conn.execute(
        """SELECT * FROM wallet_audit_logs WHERE user_id = %s AND action_type = 'DEBIT'
           ORDER BY "timestamp" DESC, id DESC LIMIT 1""",
        [user_id],
    ).fetchone()
    return {
        "order": order,
        "balance_before": audit["balance_after"] + audit["amount_changed"],
        "balance_after": audit["balance_after"],
        "audit_entry": audit,
    }


@app.post("/api/checkout")
def checkout(body: CheckoutRequest):
    """CALL sp_execute_checkout (it owns its REPEATABLE READ transaction) -> read results.
    Any error => the procedure has rolled back; the SQLSTATE is mapped to a friendly message (errors.py)."""
    amount = body.amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
    _check_amount(amount)
    for attempt in range(3):
        with db.pool.connection() as conn:
            conn.autocommit = True  # the procedure does its own COMMIT / ROLLBACK
            try:
                return _checkout_once(conn, body.user_id, body.restaurant_id, amount)
            except Exception as exc:
                retry = isinstance(exc, psycopg.Error) and exc.sqlstate in _RETRY_STATES
                if retry and attempt < 2:
                    continue  # concurrent update: try again with a fresh snapshot
                raise
            finally:
                try:
                    conn.autocommit = False
                except psycopg.Error:
                    pass


# ---------------------------------------------------------------------- audit trail
@app.get("/api/users/{user_id}/audit")
def audit_trail(
    user_id: UUID,
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    tz: Optional[str] = Query(None, max_length=64),
):
    """Dates are whole days in the caller's time zone (?tz=Asia/Kolkata from the browser); IST if not given/invalid."""
    zone, zone_name = _resolve_tz(tz)
    user = db.one("SELECT id, name, wallet_balance FROM users WHERE id = %s", [user_id])
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "User not found.")
    clauses, params = ["user_id = %s"], [user_id]
    if date_from:
        clauses.append('"timestamp" >= %s')
        params.append(datetime.combine(date_from, datetime.min.time(), tzinfo=zone))
    if date_to:  # inclusive end date
        clauses.append('"timestamp" < %s')
        params.append(datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=zone))
    where = " AND ".join(clauses)
    totals = db.one(
        f"""SELECT COUNT(*) AS n,
                   COALESCE(SUM(amount_changed) FILTER (WHERE action_type = 'DEBIT'), 0)  AS total_debits,
                   COALESCE(SUM(amount_changed) FILTER (WHERE action_type = 'CREDIT'), 0) AS total_credits
            FROM wallet_audit_logs WHERE {where}""",
        params,
    )
    # balance_after IS the running balance the DB recorded after each change.
    items = db.all(
        f"""SELECT id, action_type, amount_changed,
                   CASE WHEN action_type = 'DEBIT' THEN -amount_changed ELSE amount_changed END AS signed_amount,
                   balance_after AS running_balance,
                   balance_after - CASE WHEN action_type = 'DEBIT' THEN -amount_changed ELSE amount_changed END
                       AS balance_before,
                   "timestamp"
            FROM wallet_audit_logs WHERE {where}
            ORDER BY "timestamp" DESC, id DESC LIMIT %s OFFSET %s""",
        params + [limit, (page - 1) * limit],
    )
    out = _paged(items, totals["n"], page, limit)
    out.update(user=user, total_debits=totals["total_debits"], total_credits=totals["total_credits"], timezone=zone_name)
    return out


# ----------------------------------------------- Workflow 2: window analytics + MV
@app.get("/api/analytics/moving-average")
def moving_average(restaurant_id: UUID):
    """7-day moving average series for one restaurant (query from sql/06_window_analytics.sql)."""
    r = _restaurant_or_404(restaurant_id)
    rows = db.all(
        f"SELECT * FROM (\n{_window_sql()}\n) w WHERE w.restaurant_id = %s ORDER BY w.revenue_date",
        [restaurant_id],
    )
    series = [
        {"date": x["revenue_date"], "daily_revenue": x["daily_revenue"], "moving_avg_7_day": x["moving_avg_7_day"]}
        for x in rows
    ]
    return {
        "restaurant_id": r["id"],
        "restaurant_name": r["name"],
        "period_revenue": rows[0]["period_revenue"] if rows else 0,
        "revenue_rank": rows[0]["revenue_rank"] if rows else None,
        "series": series,
    }


@app.get("/api/analytics/ranking")
def ranking(limit: int = Query(20, ge=1, le=100)):
    """DENSE_RANK() table of restaurants by revenue over the analysed period."""
    items = db.all(
        f"""SELECT DISTINCT w.restaurant_id, r.name AS restaurant_name, w.period_revenue, w.revenue_rank
            FROM (\n{_window_sql()}\n) w JOIN restaurants r ON r.id = w.restaurant_id
            ORDER BY w.revenue_rank, restaurant_name LIMIT %s""",
        [limit],
    )
    return {"items": items}


@app.get("/api/analytics/summary")
def analytics_summary():
    """Totals from the materialized view + last refresh time."""
    last = _last_refreshed()
    try:
        totals = db.one(
            """SELECT COUNT(DISTINCT restaurant_id) AS restaurants, COALESCE(SUM(order_count), 0) AS total_orders,
                      COALESCE(SUM(daily_revenue), 0) AS total_revenue FROM mv_restaurant_daily_revenue"""
        )
        top = db.all(
            """SELECT m.restaurant_id, r.name AS restaurant_name, SUM(m.order_count) AS order_count,
                      SUM(m.daily_revenue) AS revenue
               FROM mv_restaurant_daily_revenue m JOIN restaurants r ON r.id = m.restaurant_id
               GROUP BY m.restaurant_id, r.name ORDER BY revenue DESC LIMIT 5"""
        )
    except psycopg.errors.ObjectNotInPrerequisiteState:
        return {"populated": False, "last_refreshed": last, "restaurants": 0, "total_orders": 0,
                "total_revenue": 0, "top_restaurants": []}
    return {"populated": True, "last_refreshed": last, "restaurants": totals["restaurants"],
            "total_orders": totals["total_orders"], "total_revenue": totals["total_revenue"],
            "top_restaurants": top}


@app.post("/api/analytics/refresh")
def analytics_refresh():
    """Refresh both revenue views; each refresh is logged in mv_refresh_log by the database."""
    try:
        db.run("SELECT fn_refresh_all_revenue_views()")
    except psycopg.errors.UndefinedFunction:
        # Older database without sql/05's refresh log: refresh the summary's view directly.
        try:
            db.run("SELECT fn_refresh_restaurant_daily_revenue()")
        except (psycopg.errors.FeatureNotSupported, psycopg.errors.ObjectNotInPrerequisiteState):
            # MV was created WITH NO DATA: CONCURRENTLY needs a first plain refresh.
            db.run("REFRESH MATERIALIZED VIEW mv_restaurant_daily_revenue")
    _last_refresh_memory["at"] = datetime.now(timezone.utc)
    return {"last_refreshed": _last_refreshed()}


# ------------------------------------------------ Workflow 3: nearest active driver
@app.get("/api/drivers/nearby")
def drivers_nearby(
    lng: Optional[float] = Query(None, ge=-180, le=180),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    restaurant_id: Optional[UUID] = None,
    radius: int = Query(5000, ge=100, le=50000),
    limit: int = Query(20, ge=1, le=100),
    fresh_minutes: int = Query(DRIVER_FRESH_MINUTES, ge=1, le=240),
):
    """$geoNear around a point (or a restaurant). One row per driver (their latest ping),
    active drivers only, sorted by distance. Poll this endpoint for live updates."""
    if restaurant_id is not None:
        r = _restaurant_or_404(restaurant_id)
        lng, lat = r["longitude"], r["latitude"]
    if lng is None or lat is None:
        raise ApiError(400, "VALIDATION_ERROR", "Provide lng & lat, or a restaurant_id.")
    since = datetime.now(timezone.utc) - timedelta(minutes=fresh_minutes)
    pipeline = [
        {"$geoNear": {
            "near": {"type": "Point", "coordinates": [lng, lat]},
            "distanceField": "distance_m",
            "maxDistance": radius,
            "spherical": True,
            "query": {"created_at": {"$gte": since}},
        }},
        {"$sort": {"created_at": -1}},                                   # newest ping first
        {"$group": {"_id": "$driver_id", "doc": {"$first": "$$ROOT"}}},  # latest ping per driver
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$match": {"active": True}},
        {"$sort": {"distance_m": 1}},
        {"$limit": limit},
        {"$project": {
            "_id": 0, "driver_id": 1, "active": 1, "created_at": 1,
            "distance_m": {"$round": ["$distance_m", 0]},
            "lng": {"$arrayElemAt": ["$location.coordinates", 0]},
            "lat": {"$arrayElemAt": ["$location.coordinates", 1]},
        }},
    ]
    items = list(db.mongo["DriverPings"].aggregate(pipeline, allowDiskUse=True))
    return {
        "origin": {"lng": lng, "lat": lat},
        "radius_m": radius,
        "server_time": datetime.now(timezone.utc),
        "items": items,
    }


# --------------------------------------------------- Workflow 4: review analytics
@app.get("/api/restaurants/{restaurant_id}/reviews/analytics")
def review_analytics(restaurant_id: UUID, mongo_key: Optional[str] = None):
    """$facet: rating distribution, most frequent tags ($unwind), overall average."""
    _restaurant_or_404(restaurant_id)
    keys = _mongo_keys(restaurant_id, mongo_key)
    pipeline = [
        {"$match": {"restaurant_id": {"$in": keys}}},
        {"$facet": {
            "rating_distribution": [
                {"$group": {"_id": "$rating", "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ],
            "most_frequent_tags": [
                {"$unwind": "$sentiment_tags"},
                {"$group": {"_id": "$sentiment_tags", "count": {"$sum": 1}}},
                {"$sort": {"count": -1, "_id": 1}},
                {"$limit": 10},
            ],
            "overall_average_rating": [
                {"$group": {"_id": None, "average": {"$avg": "$rating"}, "total": {"$sum": 1}}},
            ],
        }},
    ]
    res = next(db.mongo["Reviews"].aggregate(pipeline), {})
    counts = {int(d["_id"]): d["count"] for d in res.get("rating_distribution", [])}
    overall = (res.get("overall_average_rating") or [{}])[0]
    return {
        "restaurant_id": restaurant_id,
        "total_reviews": overall.get("total", 0),
        "average_rating": round(overall["average"], 2) if overall.get("average") is not None else None,
        "rating_distribution": [{"rating": s, "count": counts.get(s, 0)} for s in range(1, 6)],
        "top_tags": [{"tag": d["_id"], "count": d["count"]} for d in res.get("most_frequent_tags", [])],
    }
