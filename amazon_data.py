"""
amazon_data.py
Fetches sales and inventory data from Supabase for use in the forecast app.
End date is always yesterday (today - 1 day) so only fully-completed days are counted.
"""

import os
from datetime import date, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# Support both local .env and Streamlit Cloud secrets
def _get_secret(key: str) -> str:
    try:
        import streamlit as st
        return st.secrets.get(key) or os.getenv(key)
    except Exception:
        return os.getenv(key)

SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_KEY = _get_secret("SUPABASE_SERVICE_ROLE_KEY")


def _get_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_sales_end_date() -> date:
    """Always returns yesterday — so we only count fully completed days."""
    return date.today() - timedelta(days=1)


def fetch_amazon_sales(period_days: int, end_date: date = None):
    """
    Query Supabase orders table for units sold per ASIN over a period.

    Parameters:
        period_days : int  — 7, 14, 30, 60, or 90
        end_date    : date — defaults to yesterday

    Returns:
        (results, zero_unit_asins) — same format as sellerboard_parser.parse_sellerboard_report()
    """
    if end_date is None:
        end_date = get_sales_end_date()

    start_date = end_date - timedelta(days=period_days)

    client = _get_client()

    # Paginate to get ALL rows (Supabase default limit is 1000)
    all_rows = []
    page_size = 1000
    page = 0
    while True:
        resp = (
            client.table("orders")
            .select("asin, sku, product_name, quantity, purchase_date, order_status")
            .gte("purchase_date", start_date.isoformat())
            .lte("purchase_date", end_date.strftime("%Y-%m-%dT23:59:59"))
            .range(page * page_size, (page + 1) * page_size - 1)
            .execute()
        )
        all_rows.extend(resp.data)
        if len(resp.data) < page_size:
            break
        page += 1

    # Aggregate by ASIN
    asin_totals: dict = {}
    for row in all_rows:
        status = (row.get("order_status") or "").strip()
        if status in ("Cancelled", "Pending", "canceled"):
            continue

        asin = (row.get("asin") or "").strip()
        if not asin:
            continue

        sku   = (row.get("sku") or "").strip()
        title = (row.get("product_name") or "").strip()
        qty   = int(row.get("quantity") or 0)

        if asin not in asin_totals:
            asin_totals[asin] = {
                "child_asin":   asin,
                "parent_asin":  asin,
                "sku":          sku,
                "title":        title,
                "units_ordered": 0,
                "report_days":  period_days,
                "start_date":   start_date,
                "end_date":     end_date,
            }
        asin_totals[asin]["units_ordered"] += qty

    results = []
    zero_unit_asins = []
    for asin, data in asin_totals.items():
        if data["units_ordered"] == 0:
            zero_unit_asins.append(asin)
        else:
            data["daily_velocity"] = round(data["units_ordered"] / period_days, 4)
            results.append(data)

    # Sort by units descending
    results.sort(key=lambda x: x["units_ordered"], reverse=True)
    return results, zero_unit_asins


def fetch_all_periods(end_date: date = None) -> dict:
    """
    Fetch sales for all 5 periods in one call.
    Returns dict keyed by period ('7_day', '14_day', etc.)
    """
    if end_date is None:
        end_date = get_sales_end_date()

    periods = [7, 14, 30, 60, 90]
    all_results = {}
    for days in periods:
        results, _ = fetch_amazon_sales(days, end_date)
        all_results[f"{days}_day"] = results
    return all_results


def fetch_inventory() -> dict:
    """
    Fetch inventory from Supabase (AWD + any FBA data available).
    Returns dict keyed by SKU: {sku, asin, awd_quantity, fba_available, fba_inbound, ...}
    """
    client = _get_client()
    resp = client.table("inventory").select("*").execute()
    return {row["sku"]: row for row in resp.data}


def fetch_inventory_by_asin() -> dict:
    """
    Same as fetch_inventory() but keyed by ASIN for easy lookup in the forecast app.
    """
    by_sku = fetch_inventory()
    by_asin = {}
    for sku, row in by_sku.items():
        asin = row.get("asin")
        if asin:
            by_asin[asin] = row
    return by_asin
