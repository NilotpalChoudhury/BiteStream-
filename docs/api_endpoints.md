# BiteStream API – endpoint reference

Base URL: `http://localhost:8000` · All bodies/responses are JSON · CORS enabled.
Stack: Python 3.12, FastAPI, psycopg 3 (Postgres), pymongo (Mongo). Code in `api/`.

**Conventions**
- Lists are always paginated: `?page=1&limit=20` (limit 1–100) → `{items, total, page, limit}`.
- IDs are UUID strings. Money is returned as numbers.
- Errors always look like `{ "error_code": "...", "message": "friendly text", "sqlstate": "23505" }`
  (`sqlstate` only for DB-originated errors). Status: 400 bad input · 404 not found · 409 business rule · 500 server.

## Browse
| Method & path | Input | Output |
|---|---|---|
| `GET /api/users` | `page, limit, q` (name search) | `{items:[{id,name,wallet_balance}], total,…}` |
| `GET /api/users/{id}` | – | `{id,name,wallet_balance, recent_orders:[{id,restaurant_name,total_amount,status,created_at}]}` (last 10) |
| `POST /api/users/{id}/topup` | `{amount}` | `{user, audit_entry}` – demo helper, fires the trigger (CREDIT row) |
| `GET /api/restaurants` | `page, limit, q` | `{items:[{id,name,latitude,longitude}], total,…}` |
| `GET /api/restaurants/{id}` | `mongo_key?` | restaurant + `menu` (Mongo doc or null) + `menu_found` |
| `GET /api/restaurants/{id}/menu` | `mongo_key?` | the Mongo menu document, 404 if none |
| `GET /api/orders` | `page, limit, status, user_id, restaurant_id` | `{items:[{id,user_id,user_name,restaurant_id,restaurant_name,total_amount,status,created_at}], total,…}` |
| `GET /api/orders/{id}` | – | one order (same fields) |
| `POST /api/orders/{id}/advance` | – | updated order. PREPARING→DELIVERING→DELIVERED; 409 `ALREADY_DELIVERED` after that. Frees the user's active-order slot (partial unique index demo). |

## Workflow 1 – Checkout (`sp_execute_checkout`)
`POST /api/checkout` body `{ "user_id": uuid, "restaurant_id": uuid, "amount": 120.50 }`

Runs on ONE connection: `BEGIN ISOLATION LEVEL REPEATABLE READ` → read balance → `CALL sp_execute_checkout` → read new order, newest audit row, new balance → `COMMIT`. Any error → `ROLLBACK`. Serialization failures (`40001`) are retried up to 3 times.

Success `200`:
```json
{ "order": {"id":"…","user_id":"…","restaurant_id":"…","total_amount":120.0,"status":"PREPARING","created_at":"…"},
  "balance_before": 500.0, "balance_after": 380.0,
  "audit_entry": {"id":"…","user_id":"…","amount_changed":120.0,"action_type":"DEBIT","balance_after":380.0,"timestamp":"…"} }
```
| SQLSTATE | HTTP | `error_code` | Message shown to user |
|---|---|---|---|
| `P0001` / `23514` | 409 | `INSUFFICIENT_BALANCE` | Not enough wallet balance… |
| `23505` | 409 | `ACTIVE_ORDER_EXISTS` | You already have an order in progress… |
| `22023` | 400 | `INVALID_AMOUNT` | Amount must be greater than zero |
| `23503` / no user row | 404 | `NOT_FOUND` / `USER_NOT_FOUND` | User or restaurant does not exist |
| `40001`,`40P01` (after retries) | 409 | `CONCURRENT_UPDATE` | Please try again |
| bad JSON/UUID | 400 | `VALIDATION_ERROR` | Invalid input for 'field' |

## Audit trail
`GET /api/users/{id}/audit?from=YYYY-MM-DD&to=YYYY-MM-DD&page&limit` (dates inclusive, UTC, optional)
```json
{ "user": {"id":"…","name":"…","wallet_balance":380.0}, "total": 2, "total_debits": 120.0, "total_credits": 25.0,
  "items": [ {"id":"…","action_type":"DEBIT","amount_changed":120.0,"signed_amount":-120.0,
              "balance_before":500.0,"running_balance":380.0,"timestamp":"…"} ] }
```
Newest first. `running_balance` = the `balance_after` the trigger recorded.

## Workflow 2 – Analytics (window query + materialized view)
| Method & path | Output |
|---|---|
| `GET /api/analytics/moving-average?restaurant_id=` | `{restaurant_id, restaurant_name, period_revenue, revenue_rank, series:[{date,daily_revenue,moving_avg_7_day}]}` – runs `sql/06_window_analytics.sql` (path from `SQL_DIR`) |
| `GET /api/analytics/ranking?limit=20` | `{items:[{restaurant_id,restaurant_name,period_revenue,revenue_rank}]}` – `DENSE_RANK()` from the same query |
| `GET /api/analytics/summary` | `{populated, last_refreshed, restaurants, total_orders, total_revenue, top_restaurants[5]}` from `mv_restaurant_daily_revenue`. `populated:false` if never refreshed. |
| `POST /api/analytics/refresh` | `{last_refreshed}` – calls `fn_refresh_restaurant_daily_revenue()`; if the MV was never populated it falls back to one plain `REFRESH` first. |

`last_refreshed` is read from `mv_refresh_log.refreshed_at` if that table exists (Aditya's planned addition); otherwise the API remembers the time of the last refresh it performed (lost on API restart).

## Workflow 3 – Map (`$geoNear`)
`GET /api/drivers/nearby?lng=78.4867&lat=17.385` **or** `?restaurant_id=<uuid>`; optional `radius` (m, default 5000), `limit` (20), `fresh_minutes` (30)
```json
{ "origin":{"lng":78.4867,"lat":17.385}, "radius_m":5000, "server_time":"…",
  "items":[ {"driver_id":17,"distance_m":412,"active":true,"lng":78.49,"lat":17.38,"created_at":"…"} ] }
```
One row per driver (their latest ping within `fresh_minutes`), active drivers only, nearest first. The frontend polls this every few seconds.

## Workflow 4 – Reviews (`$facet`)
`GET /api/restaurants/{id}/reviews/analytics`
```json
{ "restaurant_id":"…", "total_reviews":120, "average_rating":4.12,
  "rating_distribution":[{"rating":1,"count":3},…,{"rating":5,"count":60}],
  "top_tags":[{"tag":"tasty","count":41}] }
```
Distribution always contains ratings 1–5 (zeros filled). Menu: `GET /api/restaurants/{id}/menu`.

## Misc
`GET /api/health` → `{status, postgres, mongo}`. Interactive docs (auto-generated): `/docs`.

## Open items (depend on the database layer)
- **Restaurant key shared by Postgres and Mongo.** Mongo `restaurant_id` is currently int 1..100 while Postgres uses UUIDs. The API looks up Mongo by the Postgres UUID string (and falls back to matching `restaurant_name` for menus). Until the seeders are fixed you can pass `?mongo_key=<int>` on menu/review endpoints.
- `mv_refresh_log(refreshed_at)` – used automatically if added.
- Status transitions are a guarded `UPDATE` in the API; if Aditya adds `sp_advance_order_status`, swap the call in `advance_order`.
