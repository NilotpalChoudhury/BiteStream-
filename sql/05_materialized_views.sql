-- BiteStream | Materialized views + refresh log
-- Run after 01_schema_ddl.sql. Safe to re-run on an existing database.
--
-- mv_restaurant_revenue_summary (spec): restaurants joined with their total
--   completed (DELIVERED) order count and revenue. One row per restaurant.
-- mv_restaurant_daily_revenue (kept from the original submission): the same
--   DELIVERED orders per restaurant per day.
-- mv_refresh_log: one row per refresh of either view, so "last refreshed" is
--   stored in the database (PostgreSQL does not record it for materialized views).
--
-- REFRESH ... CONCURRENTLY needs a UNIQUE index on the view and a view that has
-- been populated once, so both views are created WITH DATA (populated at create time).

BEGIN;

-- -------------------------------------------------------------------------
-- mv_refresh_log: create it, or keep / replace an existing one
-- -------------------------------------------------------------------------
-- Required columns (an existing table is kept only if all of these match):
--   id            bigint/integer, auto-generated (identity or sequence default)
--   view_name     text/varchar
--   refreshed_at  timestamp with time zone
-- An existing table is also rejected if it is not a plain table, or if it has
-- another NOT NULL column without a default (our INSERTs would fail). A rejected
-- table is dropped and recreated (it only holds log rows).
DO $$
DECLARE
    v_kind CHAR;
    v_valid BOOLEAN;
BEGIN
    SELECT c.relkind
    INTO v_kind
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = current_schema()
      AND c.relname = 'mv_refresh_log';

    IF v_kind IS NOT NULL THEN
        v_valid := v_kind IN ('r', 'p')
            AND EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'mv_refresh_log'
                  AND column_name = 'id'
                  AND data_type IN ('bigint', 'integer')
                  AND (is_identity = 'YES' OR column_default LIKE 'nextval(%')
            )
            AND EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'mv_refresh_log'
                  AND column_name = 'view_name'
                  AND data_type IN ('text', 'character varying')
            )
            AND EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'mv_refresh_log'
                  AND column_name = 'refreshed_at'
                  AND data_type = 'timestamp with time zone'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'mv_refresh_log'
                  AND column_name NOT IN ('id', 'view_name', 'refreshed_at', 'duration_ms', 'refresh_mode')
                  AND is_nullable = 'NO'
                  AND column_default IS NULL
                  AND is_identity = 'NO'
            );

        IF v_valid THEN
            RAISE NOTICE 'mv_refresh_log exists with a compatible schema: keeping it and its rows.';
        ELSE
            RAISE NOTICE 'mv_refresh_log exists with an incompatible schema: dropping and recreating it.';
            EXECUTE CASE v_kind
                WHEN 'v' THEN 'DROP VIEW mv_refresh_log CASCADE'
                WHEN 'm' THEN 'DROP MATERIALIZED VIEW mv_refresh_log CASCADE'
                WHEN 'f' THEN 'DROP FOREIGN TABLE mv_refresh_log CASCADE'
                ELSE 'DROP TABLE mv_refresh_log CASCADE'
            END;
            v_kind := NULL;
        END IF;
    END IF;

    IF v_kind IS NULL THEN
        CREATE TABLE mv_refresh_log (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            view_name TEXT NOT NULL,
            refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            duration_ms NUMERIC(12,3),
            refresh_mode TEXT
        );
        RAISE NOTICE 'mv_refresh_log created.';
    END IF;
END;
$$;

-- Optional columns: added if a kept table lacks them.
ALTER TABLE mv_refresh_log ADD COLUMN IF NOT EXISTS duration_ms NUMERIC(12,3);
ALTER TABLE mv_refresh_log ADD COLUMN IF NOT EXISTS refresh_mode TEXT;

CREATE INDEX IF NOT EXISTS idx_mv_refresh_log_view_time
    ON mv_refresh_log (view_name, refreshed_at DESC);

COMMENT ON TABLE mv_refresh_log IS
'One row per materialized-view refresh (written by the fn_refresh_* functions). Source of "last refreshed".';

-- -------------------------------------------------------------------------
-- mv_restaurant_revenue_summary (spec)
-- -------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_restaurant_revenue_summary AS
SELECT
    r.id AS restaurant_id,
    r.name AS restaurant_name,
    COUNT(o.id) AS completed_order_count,
    COALESCE(SUM(o.total_amount), 0.00)::DECIMAL(14,2) AS total_revenue,
    MAX(o.created_at) AS last_completed_order_at
FROM restaurants AS r
LEFT JOIN orders AS o
  ON o.restaurant_id = r.id
 AND o.status = 'DELIVERED'
GROUP BY r.id, r.name
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_restaurant_revenue_summary
    ON mv_restaurant_revenue_summary (restaurant_id);

CREATE INDEX IF NOT EXISTS idx_mv_restaurant_revenue_summary_revenue
    ON mv_restaurant_revenue_summary (total_revenue DESC);

CREATE OR REPLACE FUNCTION fn_refresh_restaurant_revenue_summary()
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_started TIMESTAMPTZ := clock_timestamp();
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_restaurant_revenue_summary;

    INSERT INTO mv_refresh_log (view_name, refreshed_at, duration_ms, refresh_mode)
    VALUES (
        'mv_restaurant_revenue_summary',
        clock_timestamp(),
        EXTRACT(EPOCH FROM clock_timestamp() - v_started) * 1000,
        'CONCURRENTLY'
    );
END;
$$;

-- -------------------------------------------------------------------------
-- mv_restaurant_daily_revenue (original submission)
-- -------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_restaurant_daily_revenue AS
SELECT
    o.restaurant_id,
    DATE_TRUNC('day', o.created_at)::DATE AS revenue_date,
    COUNT(*) AS order_count,
    SUM(o.total_amount)::DECIMAL(14,2) AS daily_revenue
FROM orders AS o
WHERE o.status = 'DELIVERED'
GROUP BY o.restaurant_id, DATE_TRUNC('day', o.created_at)::DATE
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_restaurant_daily_revenue
    ON mv_restaurant_daily_revenue (restaurant_id, revenue_date);

CREATE INDEX IF NOT EXISTS idx_mv_restaurant_daily_revenue_date
    ON mv_restaurant_daily_revenue (revenue_date DESC);

CREATE OR REPLACE FUNCTION fn_refresh_restaurant_daily_revenue()
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_started TIMESTAMPTZ := clock_timestamp();
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_restaurant_daily_revenue;

    INSERT INTO mv_refresh_log (view_name, refreshed_at, duration_ms, refresh_mode)
    VALUES (
        'mv_restaurant_daily_revenue',
        clock_timestamp(),
        EXTRACT(EPOCH FROM clock_timestamp() - v_started) * 1000,
        'CONCURRENTLY'
    );
END;
$$;

-- -------------------------------------------------------------------------
-- Refresh both views (used by the Analytics "Refresh" button)
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_refresh_all_revenue_views()
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM fn_refresh_restaurant_revenue_summary();
    PERFORM fn_refresh_restaurant_daily_revenue();

    RETURN (
        SELECT MAX(refreshed_at)
        FROM mv_refresh_log
        WHERE view_name IN ('mv_restaurant_revenue_summary', 'mv_restaurant_daily_revenue')
    );
END;
$$;

-- A view with no log row yet (fresh database, or an existing database that is
-- getting the log for the first time) is refreshed once now, so the logged
-- "last refreshed" time is always a real refresh and is never empty.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM mv_refresh_log WHERE view_name = 'mv_restaurant_revenue_summary') THEN
        PERFORM fn_refresh_restaurant_revenue_summary();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM mv_refresh_log WHERE view_name = 'mv_restaurant_daily_revenue') THEN
        PERFORM fn_refresh_restaurant_daily_revenue();
    END IF;
END;
$$;

COMMIT;

-- Refresh after data changes (no read lock on the views while refreshing):
-- SELECT fn_refresh_all_revenue_views();            -- both views, returns the refresh time
-- SELECT fn_refresh_restaurant_revenue_summary();   -- one view
-- SELECT fn_refresh_restaurant_daily_revenue();     -- one view
-- Last refresh of a view:
-- SELECT MAX(refreshed_at) FROM mv_refresh_log WHERE view_name = 'mv_restaurant_daily_revenue';
