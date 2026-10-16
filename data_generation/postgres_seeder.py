#!/usr/bin/env python3
"""
PostgreSQL Data Seeder for BiteStream Platform.
Seeds realistic mock data into users, restaurants, orders, and wallet_audit_logs tables
using Faker while respecting PostgreSQL constraints, foreign keys, triggers, and indexes.

Structure follows the GigTask-P5 seeder (argparse, logging, .env, Faker, batched
execute_values, deterministic --seed, --clear, target counts, MV refresh). BiteStream rules:
- Wallet ledger is consistent: every user's wallet_balance equals the balance_after of their
  latest wallet_audit_logs row, and every DEBIT row matches exactly one order.
- Historical orders are DELIVERED and spread over the last --days days, so Workflow 2
  (7-day moving average) and the audit-trail date filter have real data to work with.
- Active orders (PREPARING / DELIVERING) are placed through sp_execute_checkout, so the
  stored procedure, the audit trigger and the partial unique index are exercised for real.
- Restaurants are placed in Hyderabad, the same area as the MongoDB driverPings.
- Demo fixtures with fixed IDs (see DEMO_USERS / DEMO_RESTAURANT) for the UI and tests.

Default targets:
- Users: 5,000 rows
- Restaurants: 200 rows
- Orders: 100,000 historical rows (+ --active-orders live rows)
- Wallet Audit Logs: at least 120,000 rows
"""

import argparse
import logging
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from faker import Faker
import psycopg2
from psycopg2.extras import execute_values

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("postgres_seeder")

# Hyderabad bounding box (same area as driverPings in mongo_seeder.py)
CITY_LAT_RANGE = (17.30, 17.55)
CITY_LON_RANGE = (78.35, 78.58)

RESTAURANT_STYLES = [
    "Biryani House", "Kitchen", "Dhaba", "Tiffins", "Pizzeria", "Burger Co.",
    "Bakery", "Cafe", "Grill", "Wok", "Mess", "Bistro", "Sweets", "Canteen"
]

# Fixed IDs so the frontend, backend and tests can rely on them.
DEMO_RESTAURANT = (
    "00000000-0000-4000-8000-0000000000a1", "Demo Restaurant (Charminar)", 17.3616, 78.4747
)
DEMO_USERS = {
    "rich": ("00000000-0000-4000-8000-000000000001", "Demo User (Rich Wallet)"),
    "low": ("00000000-0000-4000-8000-000000000002", "Demo User (Low Balance)"),
    "active": ("00000000-0000-4000-8000-000000000003", "Demo User (Active Order)"),
}

CENT = Decimal("0.01")


def money(value):
    """Round a number to a DECIMAL(10,2)-compatible Decimal."""
    return Decimal(str(value)).quantize(CENT)


def new_uuid():
    """UUID drawn from the seeded RNG, so --seed gives the same IDs on every machine."""
    return str(uuid.UUID(int=random.getrandbits(128), version=4))


def get_db_connection(args):
    """Establish and return a PostgreSQL connection."""
    conn_params = {
        "host": args.host or os.getenv("PGHOST", os.getenv("DB_HOST", "localhost")),
        "port": args.port or int(os.getenv("PGPORT", os.getenv("DB_PORT", 5432))),
        "user": args.user or os.getenv("PGUSER", os.getenv("DB_USER", "postgres")),
        "password": args.password or os.getenv("PGPASSWORD", os.getenv("DB_PASSWORD", "postgres")),
        "dbname": args.dbname or os.getenv("PGDATABASE", os.getenv("DB_NAME", "bitestream")),
    }

    db_url = os.getenv("DATABASE_URL")
    if db_url and not any([args.host, args.user, args.password, args.dbname]):
        logger.info("Connecting to PostgreSQL using DATABASE_URL...")
        return psycopg2.connect(db_url)

    logger.info(
        f"Connecting to PostgreSQL at {conn_params['host']}:{conn_params['port']} "
        f"(Database: {conn_params['dbname']}, User: {conn_params['user']})..."
    )
    return psycopg2.connect(**conn_params)


def truncate_tables(cursor):
    """Truncate existing tables before seeding if requested."""
    logger.warning("Truncating tables: orders, wallet_audit_logs, users, restaurants...")
    cursor.execute("""
        TRUNCATE TABLE orders, wallet_audit_logs, users, restaurants CASCADE;
    """)
    logger.info("Tables truncated successfully.")


def get_table_count(cursor, table_name):
    """Get current row count of a table."""
    cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
    return cursor.fetchone()[0]


def seed_restaurants(cursor, fake, target_count, batch_size=5000):
    """Ensure restaurants table reaches target_count rows (demo restaurant included)."""
    current_count = get_table_count(cursor, "restaurants")
    logger.info(f"[Restaurants] Current count: {current_count:,} | Target: {target_count:,}")

    to_insert = max(0, target_count - current_count)
    if to_insert > 0:
        logger.info(f"Generating and inserting {to_insert:,} restaurants in batches of {batch_size:,}...")
        insert_query = """
            INSERT INTO restaurants (id, name, latitude, longitude)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
        """
        rows = [DEMO_RESTAURANT] if current_count == 0 else []
        while len(rows) < to_insert:
            r_id = new_uuid()
            name = f"{fake.last_name()}'s {random.choice(RESTAURANT_STYLES)}"[:160]
            lat = round(random.uniform(*CITY_LAT_RANGE), 6)
            lon = round(random.uniform(*CITY_LON_RANGE), 6)
            rows.append((r_id, name, lat, lon))

        for start in range(0, len(rows), batch_size):
            execute_values(cursor, insert_query, rows[start:start + batch_size], page_size=batch_size)
            logger.info(f"  → Inserted {min(start + batch_size, len(rows)):,} / {to_insert:,} restaurants...")

        logger.info(f"✓ Restaurants table now has {get_table_count(cursor, 'restaurants'):,} rows.")
    else:
        logger.info("✓ Restaurants table already satisfies target count.")

    # Retrieve all restaurant IDs for downstream relations
    cursor.execute("SELECT id FROM restaurants ORDER BY id;")
    return [row[0] for row in cursor.fetchall()]


def plan_wallet_ledgers(fake, user_count, restaurant_ids, order_count, audit_target, days, now):
    """
    Build users, historical orders and wallet audit rows in memory as one consistent ledger.

    Per user: an opening CREDIT at sign-up, then orders (DEBIT) and top-ups (CREDIT) in time
    order. A top-up is inserted before any order the balance can't cover, so balance_after
    never goes negative. Extra top-ups are spread around until audit rows reach audit_target.
    """
    window_end = now - timedelta(hours=2)
    window_start = now - timedelta(days=days)

    def random_time(start):
        return start + timedelta(seconds=random.uniform(0, (window_end - start).total_seconds()))

    def order_amount():
        return money(min(max(random.lognormvariate(6.1, 0.5), 80.0), 3000.0))

    # Popular restaurants get more orders, so DENSE_RANK has a real spread.
    weights = [random.lognormvariate(0, 0.7) for _ in restaurant_ids]
    cum_weights, total = [], 0.0
    for w in weights:
        total += w
        cum_weights.append(total)
    demo_restaurant_id = DEMO_RESTAURANT[0]

    # name, opening credit, sign-up time, events [(time, kind, amount, restaurant_id)]
    users = {}
    for role, (u_id, name) in DEMO_USERS.items():
        signup = window_start - timedelta(days=30)
        users[u_id] = {"name": name, "signup": signup, "events": []}
    rich, low, active = (DEMO_USERS[k][0] for k in ("rich", "low", "active"))
    users[rich]["opening"] = money(50000)
    users[rich]["events"] += [(random_time(window_start), "ORDER", order_amount(), demo_restaurant_id)
                              for _ in range(12)]
    users[low]["opening"] = money(500)
    users[low]["events"] += [(window_end - timedelta(days=5), "ORDER", money(180), demo_restaurant_id),
                             (window_end - timedelta(days=2), "ORDER", money(275), demo_restaurant_id)]
    users[active]["opening"] = money(5000)
    users[active]["events"] += [(random_time(window_start), "ORDER", order_amount(), demo_restaurant_id)
                                for _ in range(6)]

    regular_ids = []
    for _ in range(user_count - len(DEMO_USERS)):
        u_id = new_uuid()
        signup = window_start - timedelta(days=random.uniform(1, 60))
        users[u_id] = {
            "name": fake.name()[:120],
            "signup": signup,
            "opening": money(random.choice([500, 1000, 2000, 3000, 5000])),
            "events": [],
        }
        regular_ids.append(u_id)

    fixture_orders = sum(len(u["events"]) for u in users.values())
    regular_orders = max(0, order_count - fixture_orders)
    order_users = random.choices(regular_ids, k=regular_orders)
    order_restaurants = random.choices(restaurant_ids, cum_weights=cum_weights, k=regular_orders)
    for u_id, r_id in zip(order_users, order_restaurants):
        users[u_id]["events"].append((random_time(window_start), "ORDER", order_amount(), r_id))

    extra_topups = max(0, audit_target - len(users) - order_count)
    for u_id in random.choices(regular_ids, k=extra_topups):
        amount = money(random.choice([500, 1000, 2000, 5000]))
        users[u_id]["events"].append((random_time(users[u_id]["signup"]), "TOPUP", amount, None))

    user_rows, order_rows, audit_rows = [], [], []
    for u_id, u in users.items():
        balance = u["opening"]
        audit_rows.append((new_uuid(), u_id, balance, "CREDIT", balance, u["signup"]))
        prev_time = u["signup"]

        for when, kind, amount, r_id in sorted(u["events"], key=lambda e: e[0]):
            if kind == "TOPUP":
                balance += amount
                audit_rows.append((new_uuid(), u_id, amount, "CREDIT", balance, when))
            else:
                if balance < amount:
                    needed = amount - balance
                    topup = money(max(random.choice([1000, 2000, 5000]), float(needed) + 500))
                    balance += topup
                    topup_time = prev_time + (when - prev_time) / 2
                    audit_rows.append((new_uuid(), u_id, topup, "CREDIT", balance, topup_time))
                balance -= amount
                order_rows.append((new_uuid(), u_id, r_id, amount, "DELIVERED", when))
                audit_rows.append((new_uuid(), u_id, amount, "DEBIT", balance, when))
            prev_time = when

        user_rows.append((u_id, u["name"], balance))

    return user_rows, order_rows, audit_rows


def bulk_insert(cursor, label, insert_query, rows, batch_size):
    """Insert rows in batches using execute_values."""
    logger.info(f"Inserting {len(rows):,} {label} in batches of {batch_size:,}...")
    for start in range(0, len(rows), batch_size):
        execute_values(cursor, insert_query, rows[start:start + batch_size], page_size=batch_size)
        inserted = min(start + batch_size, len(rows))
        if inserted % (batch_size * 5) == 0 or inserted == len(rows):
            logger.info(f"  → Inserted {inserted:,} / {len(rows):,} {label}...")


def seed_users_orders_and_wallet_audit_logs(cursor, fake, restaurant_ids, args, batch_size=5000):
    """
    Ensure users, orders and wallet_audit_logs reach their targets as one consistent ledger.
    These tables must be seeded together (balances depend on orders), so partial data
    from an earlier run is not topped up; use --clear instead.
    """
    current_users = get_table_count(cursor, "users")
    current_orders = get_table_count(cursor, "orders")
    logger.info(f"[Users] Current count: {current_users:,} | Target: {args.users:,}")
    logger.info(f"[Orders] Current count: {current_orders:,} | Target: {args.orders:,}")

    if current_users >= args.users and current_orders >= args.orders:
        logger.info("✓ Users, orders and wallet audit logs already satisfy target counts.")
        return False
    if current_users > 0 or current_orders > 0:
        raise RuntimeError(
            "Users/orders already contain partial data. The wallet ledger must be generated in "
            "one pass, so re-run with --clear."
        )

    logger.info("Planning wallet ledgers (users → orders → audit logs)...")
    now = datetime.now(timezone.utc)
    user_rows, order_rows, audit_rows = plan_wallet_ledgers(
        fake, args.users, restaurant_ids, args.orders, args.audit_logs, args.days, now
    )

    # INSERT on users does not fire the audit trigger (it is AFTER UPDATE OF wallet_balance),
    # so opening balances are recorded by the explicit CREDIT rows planned above.
    bulk_insert(cursor, "users", "INSERT INTO users (id, name, wallet_balance) VALUES %s",
                user_rows, batch_size)
    bulk_insert(cursor, "orders",
                "INSERT INTO orders (id, user_id, restaurant_id, total_amount, status, created_at) VALUES %s",
                order_rows, batch_size)
    bulk_insert(cursor, "wallet audit logs",
                "INSERT INTO wallet_audit_logs (id, user_id, amount_changed, action_type, balance_after, timestamp) VALUES %s",
                audit_rows, batch_size)

    logger.info(f"✓ Users table now has {get_table_count(cursor, 'users'):,} rows.")
    logger.info(f"✓ Orders table now has {get_table_count(cursor, 'orders'):,} rows.")
    logger.info(f"✓ Wallet audit logs table now has {get_table_count(cursor, 'wallet_audit_logs'):,} rows.")
    return True


def seed_active_orders(conn, cursor, restaurant_ids, target_count):
    """
    Place live orders through sp_execute_checkout (Workflow 1), so the procedure, the wallet
    audit trigger and idx_active_user_order are exercised. Roughly 40% are then moved to
    DELIVERING; the rest stay PREPARING.

    sp_execute_checkout COMMITs / ROLLBACKs itself, so it must be CALLed in autocommit mode
    (not inside a transaction block). Each CALL is its own REPEATABLE READ transaction.
    """
    logger.info(f"[Active Orders] Placing {target_count:,} orders through sp_execute_checkout...")
    cursor.execute("""
        SELECT id FROM users
        WHERE wallet_balance >= 1000
          AND id NOT IN (SELECT user_id FROM orders WHERE status IN ('PREPARING', 'DELIVERING'))
          AND id <> %s
        ORDER BY id;
    """, (DEMO_USERS["low"][0],))
    candidates = [row[0] for row in cursor.fetchall() if row[0] != DEMO_USERS["active"][0]]
    chosen = [DEMO_USERS["active"][0]] + random.sample(candidates, min(len(candidates), target_count - 1))

    conn.commit()
    conn.autocommit = True
    placed, failed = [], 0
    try:
        for user_id in chosen:
            restaurant_id = DEMO_RESTAURANT[0] if user_id == DEMO_USERS["active"][0] else random.choice(restaurant_ids)
            amount = money(random.uniform(150, 900))
            try:
                cursor.execute("CALL sp_execute_checkout(%s, %s, %s);", (user_id, restaurant_id, amount))
                cursor.fetchone()  # p_order_id
                placed.append(user_id)
            except psycopg2.Error as e:
                failed += 1
                logger.warning(f"  Checkout skipped for {user_id}: {e.pgerror or e}")
    finally:
        conn.autocommit = False

    delivering = [u for u in placed if u != DEMO_USERS["active"][0] and random.random() < 0.4]
    if delivering:
        cursor.execute("""
            UPDATE orders SET status = 'DELIVERING'
            WHERE status = 'PREPARING' AND user_id = ANY(%s::uuid[]);
        """, (delivering,))

    logger.info(f"✓ Placed {len(placed):,} active orders ({len(delivering):,} DELIVERING), {failed:,} failed.")


def log_summary(cursor):
    """Log what was seeded."""
    cursor.execute("SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY status;")
    logger.info("Orders by status: " + ", ".join(f"{s}={c:,}" for s, c in cursor.fetchall()))
    cursor.execute("SELECT action_type, COUNT(*) FROM wallet_audit_logs GROUP BY action_type ORDER BY action_type;")
    logger.info("Wallet audit logs by type: " + ", ".join(f"{a}={c:,}" for a, c in cursor.fetchall()))
    cursor.execute("SELECT MIN(created_at)::date, MAX(created_at)::date FROM orders;")
    first, last = cursor.fetchone()
    logger.info(f"Order dates: {first} → {last}")
    logger.info("Demo fixtures: restaurant " + DEMO_RESTAURANT[0] + " | users "
                + ", ".join(f"{role}={u_id}" for role, (u_id, _) in DEMO_USERS.items()))


def main():
    parser = argparse.ArgumentParser(
        description="Seed PostgreSQL database with mock data for the BiteStream platform."
    )
    parser.add_argument("--users", type=int, default=5000, help="Target total number of users (default: 5000)")
    parser.add_argument("--restaurants", type=int, default=200, help="Target total number of restaurants (default: 200)")
    parser.add_argument("--orders", type=int, default=100000, help="Target number of historical (DELIVERED) orders (default: 100000)")
    parser.add_argument("--audit-logs", type=int, default=120000, help="Minimum number of wallet audit logs (default: 120000)")
    parser.add_argument("--active-orders", type=int, default=300, help="Live orders placed via sp_execute_checkout (default: 300)")
    parser.add_argument("--days", type=int, default=120, help="Spread historical orders over this many past days (default: 120)")
    parser.add_argument("--batch-size", type=int, default=5000, help="Batch size for bulk insertion (default: 5000)")
    parser.add_argument("--clear", action="store_true", help="Truncate tables before seeding to start fresh")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic data generation (default: 42)")

    # Database connection parameters (default to port 5432)
    parser.add_argument("--host", type=str, default=os.getenv("PGHOST", os.getenv("DB_HOST", "localhost")), help="PostgreSQL host (default: localhost)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", os.getenv("DB_PORT", 5432))), help="PostgreSQL port (default: 5432)")
    parser.add_argument("--user", type=str, default=os.getenv("PGUSER", os.getenv("DB_USER", "postgres")), help="PostgreSQL user (default: postgres)")
    parser.add_argument("--password", type=str, default=os.getenv("PGPASSWORD", os.getenv("DB_PASSWORD", "postgres")), help="PostgreSQL password (default: postgres)")
    parser.add_argument("--dbname", type=str, default=os.getenv("PGDATABASE", os.getenv("DB_NAME", "bitestream")), help="PostgreSQL database name (default: bitestream)")

    args = parser.parse_args()

    fake = Faker("en_IN")
    if args.seed is not None:
        Faker.seed(args.seed)
        random.seed(args.seed)

    try:
        conn = get_db_connection(args)
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        sys.exit(1)

    try:
        with conn.cursor() as cursor:
            if args.clear:
                truncate_tables(cursor)
                conn.commit()

            # 1. Seed restaurants up to target
            restaurant_ids = seed_restaurants(cursor, fake, target_count=args.restaurants, batch_size=args.batch_size)

            # 2. Seed users, historical orders and wallet audit logs as one consistent ledger
            seeded = seed_users_orders_and_wallet_audit_logs(cursor, fake, restaurant_ids, args, batch_size=args.batch_size)
            conn.commit()

            # 3. Place live orders through the Workflow 1 stored procedure
            if seeded and args.active_orders > 0:
                seed_active_orders(conn, cursor, restaurant_ids, args.active_orders)
                conn.commit()

            # 4. Refresh Materialized Views (if present)
            try:
                # Refreshes both views and records each refresh in mv_refresh_log (sql/05).
                logger.info("Refreshing materialized views (fn_refresh_all_revenue_views)...")
                cursor.execute("SELECT fn_refresh_all_revenue_views();")
                conn.commit()
                logger.info("✓ Materialized views refreshed and logged in mv_refresh_log.")
            except psycopg2.errors.UndefinedFunction:
                conn.rollback()  # older schema without the refresh log: plain refresh
                for view in ("mv_restaurant_revenue_summary", "mv_restaurant_daily_revenue"):
                    try:
                        cursor.execute("SELECT to_regclass(%s);", (f"public.{view}",))
                        if cursor.fetchone()[0]:
                            logger.info(f"Refreshing materialized view '{view}'...")
                            cursor.execute(f"REFRESH MATERIALIZED VIEW {view};")
                            conn.commit()
                            logger.info(f"✓ Materialized view '{view}' refreshed.")
                    except Exception as e:
                        conn.rollback()
                        logger.warning(f"Could not refresh materialized view {view}: {e}")

            # 5. Update planner statistics and the visibility map (needed for Index Only Scans)
            conn.commit()
            conn.autocommit = True
            logger.info("Running VACUUM ANALYZE...")
            cursor.execute("VACUUM ANALYZE;")
            conn.autocommit = False

            log_summary(cursor)

        conn.commit()
        logger.info("🎉 Database seeding completed successfully!")

    except Exception as e:
        conn.rollback()
        logger.error(f"Seeding failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
