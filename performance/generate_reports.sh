#!/usr/bin/env bash
# Regenerates the performance proof files from a seeded database:
#   performance/postgres_explain_analyzes.txt  (EXPLAIN (ANALYZE, BUFFERS))
#   performance/mongo_execution_stats.json     (explain("executionStats"))
# Usage (from the repo root, after seeding):  bash performance/generate_reports.sh
# Uses the standard PG* environment variables (or .env in the repo root) and MONGO_URI.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
DB="${PGDATABASE:-bitestream}"
MONGO_URI="${MONGO_URI:-mongodb://localhost:27017/}"
OUT_PG=performance/postgres_explain_analyzes.txt
OUT_MONGO=performance/mongo_execution_stats.json

psql -X -q -d "$DB" -c "ANALYZE;"

{
    echo "# BiteStream | PostgreSQL EXPLAIN (ANALYZE, BUFFERS)"
    echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ) | $(psql -X -At -d "$DB" -c 'SELECT version();')"
    echo "# Rows: orders=$(psql -X -At -d "$DB" -c 'SELECT count(*) FROM orders') wallet_audit_logs=$(psql -X -At -d "$DB" -c 'SELECT count(*) FROM wallet_audit_logs') users=$(psql -X -At -d "$DB" -c 'SELECT count(*) FROM users') restaurants=$(psql -X -At -d "$DB" -c 'SELECT count(*) FROM restaurants')"
    echo
    echo "=============================================================================="
    echo "1. Workflow 2: sql/06_window_analytics.sql (CTEs + 7-day moving average + DENSE_RANK)"
    echo "   Expect: Index Only Scan using idx_orders_delivered_created_at_covering (no Seq Scan on orders)"
    echo "=============================================================================="
    { echo "EXPLAIN (ANALYZE, BUFFERS)"; grep -v '^--' sql/06_window_analytics.sql; } | psql -X -d "$DB"
    echo
    echo "=============================================================================="
    echo "2. Audit trail for one user (newest 50 rows): wallet_audit_logs"
    echo "   Expect: (Bitmap) Index Scan on idx_wallet_audit_user_timestamp"
    echo "=============================================================================="
    psql -X -d "$DB" -c "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM wallet_audit_logs WHERE user_id = '00000000-0000-4000-8000-000000000001' ORDER BY timestamp DESC LIMIT 50;"
    echo
    echo "=============================================================================="
    echo "3. Active-order lookup (what the partial unique index protects)"
    echo "   Expect: Index Only Scan using idx_active_user_order"
    echo "=============================================================================="
    psql -X -d "$DB" -c "EXPLAIN (ANALYZE, BUFFERS) SELECT user_id FROM orders WHERE user_id = '00000000-0000-4000-8000-000000000003' AND status IN ('PREPARING', 'DELIVERING');"
    echo
    echo "=============================================================================="
    echo "4. Materialized view: top 10 restaurants by completed revenue"
    echo "   Expect: Index Scan using idx_mv_restaurant_revenue_summary_revenue"
    echo "=============================================================================="
    psql -X -d "$DB" -c "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM mv_restaurant_revenue_summary ORDER BY total_revenue DESC LIMIT 10;"
} > "$OUT_PG" 2>&1

mongosh --quiet "${MONGO_URI%/}/bitestream" --eval '
const restaurantId = "00000000-0000-4000-8000-0000000000a1";
const origin = db.Menus.findOne({ restaurant_id: restaurantId }).location;
const wf3 = db.DriverPings.explain("executionStats").aggregate([
    { $geoNear: { near: origin, key: "location", distanceField: "distance_from_restaurant",
                  maxDistance: 5000, spherical: true, query: { active: true } } },
    { $group: { _id: "$driver_id", distance_from_restaurant: { $first: "$distance_from_restaurant" } } },
    { $sort: { distance_from_restaurant: 1 } },
    { $limit: 10 }
]);
const wf4 = db.Reviews.explain("executionStats").aggregate([
    { $match: { restaurant_id: restaurantId } },
    { $facet: {
        rating_distribution: [{ $group: { _id: "$rating", count: { $sum: 1 } } }, { $sort: { _id: 1 } }],
        most_frequent_tags: [{ $unwind: "$sentiment_tags" }, { $group: { _id: "$sentiment_tags", count: { $sum: 1 } } },
                             { $sort: { count: -1 } }, { $limit: 10 }],
        overall_average_rating: [{ $group: { _id: null, average_rating: { $avg: "$rating" }, total_reviews: { $sum: 1 } } }]
    } }
]);
print(EJSON.stringify({
    generated: new Date(),
    server_version: db.version(),
    counts: { DriverPings: db.DriverPings.countDocuments(), Reviews: db.Reviews.countDocuments(), Menus: db.Menus.countDocuments() },
    workflow3_geonear: { expect: "GEO_NEAR_2DSPHERE on idx_driverPings_location_2dsphere, no COLLSCAN", explain: wf3 },
    workflow4_facet: { expect: "IXSCAN on idx_reviews_restaurant, no COLLSCAN", explain: wf4 }
}, null, 2, { relaxed: true }));
' > "$OUT_MONGO"

echo "Wrote $OUT_PG and $OUT_MONGO"
grep -E "Seq Scan|Index Only Scan|Index Scan|Execution Time" "$OUT_PG" | sed 's/^ */  /'
grep -o -E '"stage": "(COLLSCAN|IXSCAN|GEO_NEAR_2DSPHERE)"|"indexName": "[a-zA-Z_0-9]+"' "$OUT_MONGO" | sort | uniq -c
