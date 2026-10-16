-- BiteStream | Workflow 1: Atomic Checkout
-- PostgreSQL 14+ (tested on 18)
--
-- The procedure controls its own transaction, as the spec requires:
--   1. COMMIT the implicit transaction opened by CALL, then start a fresh
--      REPEATABLE READ transaction.
--   2. Lock the user's row, deduct the wallet balance. The CHECK constraint
--      chk_users_wallet_balance_nonnegative is what rejects an overdraft.
--      The UPDATE fires trg_users_wallet_balance_audit (DEBIT audit row).
--   3. Insert the PREPARING order. idx_active_user_order rejects a second
--      active order for the same user.
--   4. COMMIT. On a CHECK / unique / serialization failure: catch it,
--      ROLLBACK, and re-raise a clear error for the caller.
--
-- Because it COMMITs internally, CALL it OUTSIDE an explicit transaction
-- block (autocommit mode). Inside BEGIN ... it fails with
-- "invalid transaction termination".
--
--   CALL sp_execute_checkout('USER_UUID', 'RESTAURANT_UUID', 250.00);
--   -- returns one row: p_order_id
--
-- Errors (SQLSTATE):
--   22023  amount must be greater than 0
--   23503  user / restaurant does not exist
--   P0001  insufficient wallet balance (CHECK constraint violated)
--   23505  user already has an active order (partial unique index)
--   40001  concurrent checkout for the same user; safe to retry


BEGIN;

DROP PROCEDURE IF EXISTS sp_execute_checkout(UUID, UUID, DECIMAL);

CREATE OR REPLACE PROCEDURE sp_execute_checkout(
    p_user_id UUID,
    p_restaurant_id UUID,
    p_total_amount DECIMAL(10,2),
    INOUT p_order_id UUID DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_error_state TEXT;
    v_error_message TEXT;
BEGIN
    -- End the transaction opened by CALL and start a REPEATABLE READ one.
    COMMIT;
    SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;

    -- Validate checkout amount.
    IF p_total_amount IS NULL OR p_total_amount <= 0.00 THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'Checkout amount must be greater than 0';
    END IF;

    -- Verify that the restaurant exists.
    IF NOT EXISTS (
        SELECT 1
        FROM restaurants
        WHERE id = p_restaurant_id
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23503',
            MESSAGE = 'Restaurant does not exist';
    END IF;

    BEGIN
        -- Lock the user's wallet row.
        PERFORM 1
        FROM users
        WHERE id = p_user_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION USING
                ERRCODE = '23503',
                MESSAGE = 'User does not exist';
        END IF;

        -- Deduct wallet balance. The CHECK constraint rejects a negative balance.
        -- This automatically fires the wallet audit trigger.
        UPDATE users
        SET wallet_balance = wallet_balance - p_total_amount
        WHERE id = p_user_id;

        -- Create the order.
        INSERT INTO orders (
            user_id,
            restaurant_id,
            total_amount,
            status
        )
        VALUES (
            p_user_id,
            p_restaurant_id,
            p_total_amount,
            'PREPARING'
        )
        RETURNING id INTO p_order_id;

    EXCEPTION
        WHEN check_violation THEN
            v_error_state := 'P0001';
            v_error_message := 'Insufficient wallet balance';
        WHEN unique_violation THEN
            v_error_state := '23505';
            v_error_message := 'User already has an active order';
        WHEN serialization_failure THEN
            v_error_state := '40001';
            v_error_message := 'Concurrent checkout for this user, please retry';
    END;

    -- The inner block's changes are already undone; end the transaction explicitly.
    IF v_error_state IS NOT NULL THEN
        ROLLBACK;
        p_order_id := NULL;
        RAISE EXCEPTION USING
            ERRCODE = v_error_state,
            MESSAGE = v_error_message;
    END IF;

    COMMIT;
END;
$$;

COMMIT;
