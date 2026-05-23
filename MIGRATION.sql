-- =====================================================
--  MIGRATION SQL - run ONCE on your existing database
--  (works on both your local PostgreSQL and Supabase)
-- =====================================================
--
-- Adds 5 new columns to stock_prices.
-- Existing rows will have NULL values for these new columns
-- until you re-upload with the new format.

ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS total_trade_qty   BIGINT;
ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS turnover_lakhs    NUMERIC(15, 4);
ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS no_of_trades      INTEGER;
ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS delivery_qty      BIGINT;
ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS delivery_pct      NUMERIC(7, 4);

-- Verify
SELECT 'stock_prices columns added' AS status;
