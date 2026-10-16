"""Database connections. All config comes from environment variables."""
import os

from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pymongo import MongoClient

conninfo = make_conninfo(
    host=os.getenv("PGHOST", "localhost"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "bitestream"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", ""),
)

# open=False: the pool is opened in main.py's startup so import never needs a DB
pool = ConnectionPool(
    conninfo, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=False
)

mongo_client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017"),
    tz_aware=True,
    serverSelectionTimeoutMS=3000,
)
mongo = mongo_client[os.getenv("MONGO_DB", "bitestream")]


def all(sql, params=None):
    """Run a SELECT, return list of dicts."""
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def one(sql, params=None):
    """Run a SELECT, return one dict or None."""
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def run(sql, params=None):
    """Run a statement in its own transaction (committed on success)."""
    with pool.connection() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else None
