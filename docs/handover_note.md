# Handover note: inherited BiteStream database

*Team 9 (A1B). Written by Aditya Chintala, 2026-10-14.*

## How we tested it
Installed PostgreSQL 18.6 and MongoDB 8.0.34 locally (no Docker), ran the inherited scripts
**unchanged** into a throwaway database, and measured row counts, timings, query plans and data
distributions before touching anything.

## What worked
- All SQL scripts applied cleanly and could be re-run safely.
- The audit trigger logged every balance change. The audit log rejected UPDATE and DELETE. The
  partial unique index blocked a second active order (`23505`).
- The checkout procedure gave clear errors and left balances untouched on failure. Two
  simultaneous checkouts for one user were handled safely (the second got `40001`).
- WF2–WF4 ran and used indexes. The original seeder's data was internally consistent.

## What did not work
1. **Seed data:** all 200,000 orders were created on a single day (within 85 s), so the 7-day
   moving average was a single spike. There were 0 active orders. Restaurants were scattered across
   the globe while driver pings were in Hyderabad (0 of 100 restaurants near a driver). Postgres
   and Mongo used different IDs (UUID vs 1..100). Every user had ~₹1,000,000, so "insufficient
   balance" could never happen.
2. **TTL:** pings were timestamped up to 4 h in the past with a 2 h TTL, so 50.3% were deleted
   within a minute (248k left, below the required 500k).
3. **Spec deviations:**
   - The materialized view was per-day and didn't join restaurants. It was created `WITH NO DATA`,
     so its CONCURRENTLY refresh failed on every fresh install.
   - The checkout procedure didn't start its own REPEATABLE READ transaction, COMMIT, or
     catch-and-rollback, and returned no order ID.
   - WF3 used a hardcoded point and returned pings instead of distinct drivers.
   - The collection names didn't match the spec.
4. With realistic data, WF2 fell back to a **sequential scan**.

## What we changed and why
| Area | Change | Why |
|---|---|---|
| `data_generation/` | Rewrote the seeders (structure adapted from a well-built reference seeder): consistent wallet ledger, 120-day history, Hyderabad restaurants, Mongo keyed by Postgres UUIDs, pings within the TTL window, 300 live orders placed **through the real procedure**, fixed-ID demo users, `--seed`/`--clear`/`.env`. New `reviews_seeder.py` and `menus_seeder.py`. | Problems 1 and 2. Make the data demoable and identical on every teammate's machine. |
| `sql/04_stored_procedures.sql` | The procedure now COMMITs and sets REPEATABLE READ itself, relies on the CHECK constraint, catches `check_violation` / `unique_violation` / `serialization_failure`, rolls back and re-raises clear codes, and returns `p_order_id`. **Must be CALLed in autocommit mode.** | Spec wording for WF1 |
| `sql/05_materialized_views.sql` | Added `mv_restaurant_revenue_summary` (restaurants LEFT JOIN completed orders) and `fn_refresh_restaurant_revenue_summary()`. Both views are now `WITH DATA`. | Spec. Fixes the broken first refresh. |
| `sql/02_indexes.sql` | Added the partial covering index `idx_orders_delivered_created_at_covering`. | WF2 now uses an Index Only Scan instead of a Seq Scan. |
| `mongo/01..03` | Renamed to `Menus` / `Reviews` / `DriverPings`, added `$jsonSchema` validators, WF3 starts from a real restaurant's location and groups by driver, WF4 uses a valid sample ID. | Spec |
| `docs/`, `performance/`, `README.md` | Regenerated the ERD (PNG + SVG), the Mongo schema map and the EXPLAIN / executionStats evidence for the fixed schema, added `performance/generate_reports.sh` to regenerate them, and rewrote the README setup. | Keep the documentation and evidence in line with the fixes |

**Later, during integration with our API/UI:** a `mv_refresh_log` table so "last refreshed" is
stored in the database, a live driver-ping generator for the map, and amount-limit / time-zone fixes.

Unchanged on purpose: the table DDL, the trigger, the partial index, the WF2 query, the WF4
pipeline and the original daily MV. They already met the spec.

## Suggestions for the original authors
- Look at the **data** your seeder produces (dates, statuses, locations, balances), not just the
  row counts. A query can be correct and still demo nothing.
- Make sure everything that crosses databases (IDs, coordinates, names) comes from one source.
- Check timestamp ranges against TTL indexes.
- Read the spec wording literally for each workflow.
- Re-run the EXPLAIN evidence after changing the data: with realistic data, WF2 switched to a
  sequential scan until a covering index was added.
