# 9_a1b: BiteStream (Team 9)

**Repository:** https://github.com/anujshandillya/BiteStream_9_a1b  
**Final commit hash:** e597289fa23b29e3bca594fc7e186540950e361c  
**Demo video:** https://www.youtube.com/watch?v=PMdj4L-iki0

CS6.302 Software System Development, Assignment 1B (Front End Design). We inherited another team's Assignment 1 database for **Project 1: BiteStream** (food delivery + real-time driver logistics, on PostgreSQL + MongoDB), verified and fixed it, and are building an API and web front end on top.

| Doc | What's in it |
|---|---|
| [`docs/handover_note.md`](docs/handover_note.md) | One-page handover: what worked, what didn't, what we changed and why |
| [`docs/relational_erd.png`](docs/relational_erd.png) | PostgreSQL ERD |
| [`docs/mongo_schema_map.json`](docs/mongo_schema_map.json) | MongoDB document structures, validators, indexes |
| [`performance/`](performance/) | Raw `EXPLAIN (ANALYZE, BUFFERS)` and `explain("executionStats")` output + the script that regenerates it |
| [`docs/api_endpoints.md`](docs/api_endpoints.md) | API endpoint and request/response contract |
| [`docs/design/`](docs/design/) | User goals and screen wireframes/design references |

## Repository structure

```
9_a1b/
├── sql/                 # PostgreSQL: schema, indexes, triggers, checkout procedure, MVs, WF2 query
├── mongo/               # MongoDB: collections + validators + indexes, WF3 $geoNear, WF4 $facet
├── data_generation/     # seeders (Postgres, DriverPings, Reviews, Menus) + requirements.txt
├── performance/         # EXPLAIN evidence + generate_reports.sh
├── docs/                # handover note, ERD, Mongo schema map, design, API
├── api/                 # server layer (Vedant)
└── web/                 # front end (Anuj)
```

## Setup (Docker, recommended)

`docker compose watch` runs PostgreSQL 18, MongoDB 7, the API (FastAPI, port 8000), the web app (Vite, port 5173) and a live driver-ping generator. On a fresh volume, Postgres runs `sql/` and Mongo runs `mongo/01_collections_and_indexes.js` automatically. **Seeding is a separate step** (below).

**Prerequisites:** Docker Desktop (running), Python 3.10+ for the seeders. Ports 5432, 27017, 8000 and 5173 must be free (stop a local Postgres / MongoDB if you have one, e.g. `brew services stop postgresql@18`).

```bash
# 1. Configuration (compose and the seeders both read .env)
cp .env.example .env                       # keep PGUSER=postgres / PGPASSWORD=postgres

# 2. Images (the compose file never pulls them itself)
docker pull postgres:18-alpine && docker pull mongo:7.0.40-jammy

# 3. Start everything (keep this terminal open)
docker compose watch                        # first run builds the api / web images

# 4. Seed, in a second terminal (about 15 s). Postgres FIRST: the Mongo seeders read Postgres ids.
python3 -m venv data_generation/.venv
data_generation/.venv/bin/pip install -r data_generation/requirements.txt
cd data_generation
.venv/bin/python postgres_seeder.py --clear
.venv/bin/python mongo_seeder.py
.venv/bin/python reviews_seeder.py
.venv/bin/python menus_seeder.py
cd ..
```

Open **http://localhost:5173** (web) · **http://localhost:8000/docs** (API docs) · **http://localhost:8000/api/health** (health check).

- **Database already initialised from older `sql/` files?** Init scripts only run on an empty volume. Either reset (`docker compose down -v`, then steps 3–4), or apply the changed file in place:
  `docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/05_materialized_views.sql'`.
- **Live driver pings:** the `live-pings` service inserts 150 drivers' positions every 5 s, so the map always has fresh, moving drivers (`LIVE_PINGS_INTERVAL` / `LIVE_PINGS_DRIVERS` in `.env` to tune; `docker compose logs -f live-pings` to watch). Without Docker: `cd data_generation && .venv/bin/python live_pings.py`.

**Without Docker:** install PostgreSQL 14+ and MongoDB 7+ locally, set `.env` to your local user, then `createdb bitestream`, `for f in sql/0[1-5]*.sql; do psql -v ON_ERROR_STOP=1 -d bitestream -f "$f"; done`, `mongosh mongo/01_collections_and_indexes.js`, and run the four seeders as above. Run the API from `api/` (`uvicorn main:app --port 8000`) and the web app from `web/` (`yarn dev`).

**Run the workflows / evidence directly** (with the local tools, or via `docker compose exec`):

```bash
psql -d bitestream -f sql/06_window_analytics.sql   # WF2
mongosh mongo/02_workflow3_geonear.js               # WF3
mongosh mongo/03_workflow4_facet.js                 # WF4
bash performance/generate_reports.sh                # EXPLAIN / executionStats files
```

**Expected data (default flags):** 5,000 users · 200 restaurants · 100,300 orders (100,000 DELIVERED + ~188 PREPARING + ~112 DELIVERING) · 129,966 wallet audit rows · 200 menus · 110,000 reviews · 510,000 seeded driver pings (plus the live ones).

**Demo fixtures (fixed IDs on every machine):**

| Fixture | ID | Use |
|---|---|---|
| Demo Restaurant (Charminar) | `00000000-0000-4000-8000-0000000000a1` | has a menu, reviews, and drivers within 5 km |
| Demo User (Rich Wallet) | `00000000-0000-4000-8000-000000000001` | checkout succeeds |
| Demo User (Low Balance) | `00000000-0000-4000-8000-000000000002` | ₹45, so checkout fails: insufficient balance |
| Demo User (Active Order) | `00000000-0000-4000-8000-000000000003` | has a PREPARING order, so checkout fails: active order |

**Workflow 1 (checkout)** must be called in **autocommit mode** (not inside `BEGIN … COMMIT`), because the procedure manages its own REPEATABLE READ transaction (the API does this):

```sql
CALL sp_execute_checkout('<user_uuid>', '<restaurant_uuid>', 250.00);   -- returns p_order_id
```

Errors: `P0001` insufficient balance · `23505` user already has an active order · `22023` amount ≤ 0 · `23503` unknown user/restaurant · `40001` concurrent checkout (retry).

## Screenshots

### Browse

![Browse screen](docs/screenshots/browse.png)

### Checkout

![Checkout screen](docs/screenshots/checkout.png)

### Wallet audit

![Wallet audit screen](docs/screenshots/wallet_audit.png)

### Analytics

![Analytics screen](docs/screenshots/revenue_analytics.png)

### Drivers

![Nearby drivers screen](docs/screenshots/live_drivers.png)

### Reviews

![Reviews screen](docs/screenshots/reviews.png)

## Tests

```bash
# API (needs the stack running and the database seeded; uses throw-away test users)
docker compose exec backend sh -c "pip install -q -r requirements-dev.txt && python -m pytest -q"

# Web (pure contract / validation tests)
cd web && node --test tests/*.test.mjs
```

| Suite | Covers |
|---|---|
| `api/tests/test_checkout.py` | Checkout success (balance before/after, DEBIT audit row), insufficient balance (rolled back, no order, no audit row), second active order blocked until the first is delivered, invalid / too-large amounts, unknown user / restaurant, top-up CREDIT and balance-overflow rejection |
| `api/tests/test_analytics_audit_map.py` | Refresh updates both materialized views and logs them; "last refreshed" comes from the log; audit date filter time zone (browser zone or IST fallback); nearby drivers are distinct, active, ≤ 5 km and sorted |
| `web/tests/api-contracts.test.mjs` | API response adapters, error messages, amount validation in the browser (incl. top-up balance limit), browser time zone |

## Database: performance proof (EXPLAIN)

Full raw output: [`performance/postgres_explain_analyzes.txt`](performance/postgres_explain_analyzes.txt), [`performance/mongo_execution_stats.json`](performance/mongo_execution_stats.json).

| Query | Plan | Time |
|---|---|---|
| WF2: 7-day moving average + DENSE_RANK (reads ~74k orders) | Index Only Scan on `idx_orders_delivered_created_at_covering`, **no Seq Scan** | ~75 ms |
| Audit trail for one user | Bitmap Index Scan on `idx_wallet_audit_user_timestamp` | 0.04 ms |
| Active-order lookup | Index Only Scan on `idx_active_user_order` | 0.04 ms |
| MV top 10 by revenue | Index Scan on `idx_mv_restaurant_revenue_summary_revenue` | 0.2 ms |
| WF3: `$geoNear` nearest active drivers within 5 km | `GEO_NEAR_2DSPHERE` on `idx_driverPings_location_2dsphere`, **no COLLSCAN** | ~92 ms |
| WF4: `$facet` review analytics | `IXSCAN` on `idx_reviews_restaurant` (573 examined / 573 returned), **no COLLSCAN** | ~1 ms |

Excerpt (WF2):

```
->  Index Only Scan using idx_orders_delivered_created_at_covering on orders o
      (cost=0.42..1786.36 rows=33331 width=26) (actual time=0.045..18.856 rows=74108.00 loops=1)
Execution Time: 75.035 ms
```

## Changes to the inherited database

Summary below; the reasons and evidence are in [`docs/handover_note.md`](docs/handover_note.md).

| File | Change |
|---|---|
| `data_generation/postgres_seeder.py` | Rewritten: consistent wallet ledger, 120-day order history, Hyderabad restaurants, 300 live orders via `sp_execute_checkout`, demo fixtures, `--seed` / `--clear` / `.env`, `VACUUM ANALYZE` at the end |
| `data_generation/mongo_seeder.py` | Seeds only `DriverPings` (510k, timestamps inside the 2 h TTL window) |
| `data_generation/reviews_seeder.py`, `menus_seeder.py` | New: keyed by Postgres UUIDs |
| `data_generation/requirements.txt`, `.env.example` | Added Faker, python-dotenv, env template |
| `sql/02_indexes.sql` | Added the covering partial index `idx_orders_delivered_created_at_covering` |
| `sql/04_stored_procedures.sql` | `sp_execute_checkout` now owns its REPEATABLE READ transaction, relies on the CHECK constraint, catches + rolls back + re-raises, returns `p_order_id` |
| `sql/05_materialized_views.sql` | Added `mv_restaurant_revenue_summary` + `fn_refresh_restaurant_revenue_summary()`. Both MVs created `WITH DATA`. |
| `mongo/01_collections_and_indexes.js` | Collections renamed `Menus` / `Reviews` / `DriverPings`. `$jsonSchema` validators. Unique menu index per restaurant. |
| `mongo/02_workflow3_geonear.js` | Origin = the restaurant's location. Results grouped per driver. |
| `mongo/03_workflow4_facet.js` | Collection name + a valid restaurant id |
| `docs/`, `performance/` | ERD, Mongo schema map and EXPLAIN evidence regenerated for the fixed schema (`performance/generate_reports.sh`), handover note |
| `sql/05_materialized_views.sql` (again) | `mv_refresh_log` table (created, kept, or replaced after a schema check), refresh functions log every refresh, `fn_refresh_all_revenue_views()` refreshes both views |
| `data_generation/live_pings.py` | New: live driver pings (runs as the `live-pings` compose service) |
| `data_generation/postgres_seeder.py` (again) | Final view refresh goes through `fn_refresh_all_revenue_views()` so it is logged |

## Assumptions (database)

- One city (Hyderabad): all restaurants and driver pings lie inside a Hyderabad bounding box.
- Drivers exist only in MongoDB (`driver_id` 1..2000). There is no drivers table in Postgres (not in the spec).
- `amount_changed` in the audit log is always positive; `action_type` (DEBIT/CREDIT) gives the direction.
- A user's opening balance is recorded as a CREDIT audit row by the seeder (the spec's trigger only fires on UPDATE).
- Historical orders are bulk-loaded with backdated timestamps. Live orders go through the stored procedure.
- "Completed" order = status `DELIVERED`. "Active" = `PREPARING` or `DELIVERING`.
- Seeded driver pings are short-lived (2 h TTL). The `live-pings` service keeps fresh ones coming.
- Revenue analytics count `DELIVERED` orders only. The chart and ranking are live; the summary numbers come from the materialized views and change when Refresh is pressed.
- The audit date filter uses whole days in the viewer's browser time zone (IST if unknown). Times on screen are shown in IST.
- Amounts are limited to ₹9,99,99,999.99 (`DECIMAL(10,2)`), checked in the browser, the API and the database.

## Tech choices

| Layer | Choice | Why it fits BiteStream |
|---|---|---|
| Front end | **React** | Component-based UI lets the six workflows share reusable controls for pagination, forms, status badges, loading/error states, and data panels. |
| Front-end tooling | **Vite** | Provides a fast development server and a straightforward production build, while keeping the browser app separate from the API. |
| Styling | **CSS (project stylesheets)** | Keeps the visual system lightweight and lets the team define consistent colours, typography, spacing, and responsive layouts without adding a UI-framework dependency. |
| API | **FastAPI (Python)** | Gives the browser a small HTTP/JSON layer, request validation, clear error responses, and automatically generated API documentation at `/docs`. |
| PostgreSQL access | **Psycopg 3 + connection pool** | Uses PostgreSQL directly and supports the inherited SQL schema, checkout stored procedure, audit trail, analytics queries, and materialized-view refresh functions. |
| MongoDB access | **PyMongo** | Calls the inherited MongoDB workflows for nearby drivers (`$geoNear`), review analytics (`$facet`), and menu documents. |
| Data stores | **PostgreSQL + MongoDB** | Preserves the inherited Assignment 1 data model: relational transactional/audit data stays in PostgreSQL, while driver pings, reviews, and menus use MongoDB documents and geospatial queries. |
| Tests | **pytest + Node.js built-in test runner** | Tests API workflows against the running stack and checks front-end/API response contracts and validation without requiring a separate test framework for the web tests. |

The API is intentionally a **thin middleware layer**: transaction rules, audit-trigger behaviour, window analytics, materialized-view logic, and MongoDB aggregation logic remain in the database rather than being duplicated in Python or the browser.

## Team and contributions

| Member | Role | Contributions |
|---|---|---|
| Aditya Chintala (2026201068) | Database verification & fixes | Verified the inherited database against the Assignment 1 specification; updated the seeders and database objects; fixed stored-procedure, materialized-view, index, and MongoDB workflow behaviour; prepared the ERD, MongoDB schema map, performance evidence, database guide, and handover note. |
| Vedant Bhatt (2026201041) | Backend / API | Implemented the FastAPI middleware in `api/`; connected PostgreSQL and MongoDB operations to HTTP endpoints; added request validation and consistent API error responses; exposed browse, checkout, wallet top-up/audit, analytics, nearby-driver, and review/menu functionality; documented the API contract in `docs/api_endpoints.md` and contributed API tests. |
| Anuj Sharma (2026201046) | Frontend / design | Implemented the React/Vite interface in `web/` for Browse, Checkout, Wallet Audit, Analytics, Drivers/Map, and Reviews; connected screens to the API; prepared user goals and screen design materials in `docs/design/`. |
| All active team members | Integration & submission | Coordinated the API/database/UI contract, tested the integrated application, and contributed to final README and submission checks. |
