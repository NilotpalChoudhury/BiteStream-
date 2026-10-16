"""One place that turns database errors into friendly API errors."""
import psycopg


class ApiError(Exception):
    def __init__(self, status, error_code, message, sqlstate=None):
        self.status = status
        self.error_code = error_code
        self.message = message
        self.sqlstate = sqlstate


def map_pg_error(exc: psycopg.Error) -> ApiError:
    """Translate a PostgreSQL error (by SQLSTATE) into an ApiError."""
    state = getattr(exc, "sqlstate", None)
    primary = (exc.diag.message_primary or "") if getattr(exc, "diag", None) else ""
    constraint = (exc.diag.constraint_name or "") if getattr(exc, "diag", None) else ""

    if state == "22023":
        return ApiError(400, "INVALID_AMOUNT", "The order amount must be greater than zero.", state)
    if state == "22003":  # numeric_value_out_of_range: DECIMAL(10,2) overflow
        return ApiError(400, "AMOUNT_TOO_LARGE",
                        "The amount is too large. Orders and wallet balances are limited to ₹9,99,99,999.99.", state)
    if state == "23503":
        return ApiError(404, "NOT_FOUND", "That user or restaurant does not exist.", state)
    if state == "23505":
        return ApiError(
            409, "ACTIVE_ORDER_EXISTS",
            "You already have an order in progress (preparing or on its way). "
            "Wait until it is delivered before placing another one.", state)
    if state == "23514":
        if "wallet" in constraint or "balance" in constraint or not constraint:
            return ApiError(409, "INSUFFICIENT_BALANCE",
                            "Not enough wallet balance - this would take it below zero.", state)
        return ApiError(400, "INVALID_AMOUNT", "The order amount is not valid.", state)
    if state == "P0001":
        if "insufficient" in primary.lower():
            return ApiError(409, "INSUFFICIENT_BALANCE",
                            "Not enough wallet balance to place this order.", state)
        return ApiError(409, "DB_RULE_VIOLATION", primary or "The database rejected this request.", state)
    if state in ("40001", "40P01"):
        return ApiError(409, "CONCURRENT_UPDATE",
                        "Another change happened at the same time. Please try again.", state)
    if state == "55000":
        return ApiError(409, "MV_NOT_POPULATED",
                        "The summary view has never been refreshed. Press Refresh first.", state)
    return ApiError(500, "DB_ERROR", "Something went wrong in the database.", state)
