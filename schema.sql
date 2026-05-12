-- ============================================================
-- xpro-inventory Supabase Schema
-- Run this in: Supabase Dashboard > SQL Editor > New Query
-- ============================================================

-- 1. INVENTORY TABLE
-- Tracks current inventory by SKU across FBA, AWD, and FC Processing
CREATE TABLE IF NOT EXISTS inventory (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    sku                     TEXT NOT NULL UNIQUE,
    asin                    TEXT,
    product_name            TEXT,
    condition               TEXT DEFAULT 'NewItem',

    -- FBA (Fulfillment Centers - ready to ship)
    fba_available           INTEGER DEFAULT 0,
    fba_reserved            INTEGER DEFAULT 0,  -- reserved for pending orders
    fba_inbound             INTEGER DEFAULT 0,  -- in transit to FC

    -- FC Processing (received at FC but not yet available)
    fc_processing           INTEGER DEFAULT 0,

    -- AWD (Amazon Warehousing & Distribution - bulk storage)
    awd_quantity            INTEGER DEFAULT 0,

    -- Totals
    total_quantity          INTEGER GENERATED ALWAYS AS (
                                fba_available + fba_reserved + fba_inbound + fc_processing + awd_quantity
                            ) STORED,

    last_synced_at          TIMESTAMPTZ DEFAULT NOW(),
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- 2. ORDERS TABLE
-- Stores individual orders for demand forecasting
CREATE TABLE IF NOT EXISTS orders (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    amazon_order_id         TEXT NOT NULL,
    sku                     TEXT,
    asin                    TEXT,
    product_name            TEXT,
    quantity                INTEGER DEFAULT 1,
    item_price              NUMERIC(10, 2),
    currency                TEXT DEFAULT 'USD',
    order_status            TEXT,
    fulfillment_channel     TEXT,  -- AFN (FBA) or MFN (seller-fulfilled)
    purchase_date           TIMESTAMPTZ,
    last_updated_date       TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(amazon_order_id, sku)
);

-- Index for fast date-range queries used in forecasting
CREATE INDEX IF NOT EXISTS orders_sku_purchase_date ON orders (sku, purchase_date DESC);
CREATE INDEX IF NOT EXISTS orders_purchase_date ON orders (purchase_date DESC);

-- 3. DEMAND FORECAST VIEW
-- Auto-computes velocity and days of coverage per SKU
CREATE OR REPLACE VIEW demand_forecast AS
WITH order_totals AS (
    SELECT
        sku,
        SUM(CASE WHEN purchase_date >= NOW() - INTERVAL '14 days' THEN quantity ELSE 0 END) AS units_14d,
        SUM(CASE WHEN purchase_date >= NOW() - INTERVAL '30 days' THEN quantity ELSE 0 END) AS units_30d,
        SUM(CASE WHEN purchase_date >= NOW() - INTERVAL '60 days' THEN quantity ELSE 0 END) AS units_60d,
        SUM(CASE WHEN purchase_date >= NOW() - INTERVAL '90 days' THEN quantity ELSE 0 END) AS units_90d
    FROM orders
    GROUP BY sku
)
SELECT
    i.sku,
    i.asin,
    i.product_name,
    i.fba_available,
    i.fba_reserved,
    i.fba_inbound,
    i.fc_processing,
    i.awd_quantity,
    i.total_quantity,

    -- Units sold per period
    COALESCE(o.units_14d, 0)  AS units_sold_14d,
    COALESCE(o.units_30d, 0)  AS units_sold_30d,
    COALESCE(o.units_60d, 0)  AS units_sold_60d,
    COALESCE(o.units_90d, 0)  AS units_sold_90d,

    -- Daily velocity
    ROUND(COALESCE(o.units_14d, 0) / 14.0, 2) AS daily_velocity_14d,
    ROUND(COALESCE(o.units_30d, 0) / 30.0, 2) AS daily_velocity_30d,
    ROUND(COALESCE(o.units_60d, 0) / 60.0, 2) AS daily_velocity_60d,
    ROUND(COALESCE(o.units_90d, 0) / 90.0, 2) AS daily_velocity_90d,

    -- Days of coverage (total inventory / daily velocity)
    CASE WHEN o.units_14d > 0 THEN ROUND(i.total_quantity / (o.units_14d / 14.0), 0) ELSE NULL END AS days_coverage_14d,
    CASE WHEN o.units_30d > 0 THEN ROUND(i.total_quantity / (o.units_30d / 30.0), 0) ELSE NULL END AS days_coverage_30d,
    CASE WHEN o.units_60d > 0 THEN ROUND(i.total_quantity / (o.units_60d / 60.0), 0) ELSE NULL END AS days_coverage_60d,
    CASE WHEN o.units_90d > 0 THEN ROUND(i.total_quantity / (o.units_90d / 90.0), 0) ELSE NULL END AS days_coverage_90d,

    i.last_synced_at
FROM inventory i
LEFT JOIN order_totals o ON i.sku = o.sku;
