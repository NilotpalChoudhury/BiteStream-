-- BiteStream | PostgreSQL indexes
-- Run after 01_schema_ddl.sql.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS idx_active_user_order
    ON orders (user_id)
    WHERE status IN ('PREPARING', 'DELIVERING');

CREATE INDEX IF NOT EXISTS idx_orders_restaurant_created_at
    ON orders (restaurant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_user_created_at
    ON orders (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_status_created_at
    ON orders (status, created_at DESC);

-- Workflow 2 (06_window_analytics.sql) reads every DELIVERED order in the last
-- 90 days (~75% of the table). A plain index loses to a Seq Scan at that
-- selectivity, so this covering partial index lets the query run as an
-- Index Only Scan: only DELIVERED rows, ordered by created_at, with the two
-- columns the query needs (restaurant_id, total_amount) stored in the index.
CREATE INDEX IF NOT EXISTS idx_orders_delivered_created_at_covering
    ON orders (created_at)
    INCLUDE (restaurant_id, total_amount)
    WHERE status = 'DELIVERED';

CREATE INDEX IF NOT EXISTS idx_wallet_audit_user_timestamp
    ON wallet_audit_logs (user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_wallet_audit_action_timestamp
    ON wallet_audit_logs (action_type, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_restaurants_name
    ON restaurants (name);

COMMIT;
