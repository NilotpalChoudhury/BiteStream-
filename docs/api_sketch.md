# BiteStream API sketch

Draft endpoint list for the six screens, written before building the UI. The API stays a thin
layer: each endpoint calls the database object in the last column (procedure, query, materialized
view or pipeline).

**Paginate every list** (the spec says never load 50k+ rows into the browser).

| Method & path | Input | Output | Backed by |
|---|---|---|---|
| `GET /api/users?page&limit&q` | paging, name search | `{items:[{id,name,wallet_balance}], total}` | `users` |
| `GET /api/users/:id` | — | user + recent orders | `users`, `orders` |
| `GET /api/restaurants?page&limit&q` | paging, search | list | `restaurants` |
| `GET /api/restaurants/:id` | — | restaurant + menu (Mongo) | `restaurants` + `menus` |
| `GET /api/orders?page&limit&status&user_id&restaurant_id` | filters | list | `orders` |
| `GET /api/orders/:id` | — | detail | `orders` |
| `POST /api/checkout` | `{user_id, restaurant_id, amount}` | `{order, balance_before, balance_after, audit_entry}` or `{error_code, message}` | `sp_execute_checkout` |
| `POST /api/orders/:id/advance` | — | updated order | status transition |
| `GET /api/users/:id/audit?from&to&page` | date range | rows with **running balance** | `wallet_audit_logs` |
| `GET /api/analytics/moving-average?restaurant_id` | restaurant | daily series | `06_window_analytics.sql` |
| `GET /api/analytics/ranking` | — | DENSE_RANK table | `06_window_analytics.sql` |
| `GET /api/analytics/summary` | — | MV totals + `last_refreshed` | `mv_restaurant_daily_revenue` |
| `POST /api/analytics/refresh` | — | `{last_refreshed}` | `fn_refresh_restaurant_daily_revenue()` |
| `GET /api/drivers/nearby?lng&lat&radius=5000` | origin | drivers sorted by distance | `$geoNear` pipeline |
| `GET /api/restaurants/:id/reviews/analytics` | — | facet result | `$facet` pipeline |
| `GET /api/restaurants/:id/menu` | — | menu document | `menus` |

**Checkout must run in one transaction** on one connection:
`BEGIN; SET TRANSACTION ISOLATION LEVEL REPEATABLE READ; read balance_before; CALL sp_execute_checkout(...); read new order + newest audit row + balance_after; COMMIT;`
On any error: `ROLLBACK` and map the SQLSTATE to a friendly message.
