"""
sync.py — Main sync script
Usage:
    source venv/bin/activate
    python sync.py            # sync everything (inventory + 90 days of orders)
    python sync.py --orders   # orders only
    python sync.py --inventory # inventory only
"""

import argparse
import logging
import sys
import time
from datetime import datetime

from amazon_client import AmazonClient
from supabase_client import get_supabase

logging.basicConfig(
    filename="logs/sync.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)
log = logging.getLogger(__name__)


def sync_inventory(amazon: AmazonClient, supabase):
    log.info("▶ Syncing inventory...")
    total = 0

    # --- AWD inventory (working) ---
    try:
        awd_items = amazon.get_awd_inventory()
        awd_rows = []
        for item in awd_items:
            awd_rows.append({
                "sku":              item.get("sku", ""),
                "awd_quantity":     item.get("totalOnhandQuantity", 0),
                "fba_inbound":      item.get("totalInboundQuantity", 0),
                "last_synced_at":   datetime.utcnow().isoformat(),
            })
        if awd_rows:
            supabase.table("inventory").upsert(awd_rows, on_conflict="sku").execute()
            log.info(f"  ✅ AWD inventory synced: {len(awd_rows)} SKUs")
            total += len(awd_rows)
    except Exception as e:
        log.error(f"  ❌ AWD inventory sync failed: {e}")

    # --- FBA inventory via Reports API ---
    try:
        items = amazon.get_inventory()
        if items:
            fba_rows = []
            for item in items:
                fba_rows.append({
                    "sku":           item.get("sku", ""),
                    "asin":          item.get("asin", ""),
                    "product_name":  item.get("product_name", ""),
                    "condition":     item.get("condition", "NewItem"),
                    "fba_available": item.get("fba_available", 0),
                    "fba_reserved":  item.get("fba_reserved", 0),
                    "fc_processing": item.get("fc_processing", 0),
                    "last_synced_at": datetime.utcnow().isoformat(),
                })
            supabase.table("inventory").upsert(fba_rows, on_conflict="sku").execute()
            log.info(f"  ✅ FBA inventory synced: {len(fba_rows)} SKUs")
            total += len(fba_rows)
        else:
            log.warning("  ⚠️  FBA inventory: no data returned (permissions pending)")
    except Exception as e:
        log.warning(f"  ⚠️  FBA inventory skipped: {e}")

    return total


def sync_orders(amazon: AmazonClient, supabase, days_back=90):
    log.info(f"▶ Syncing orders (last {days_back} days)...")
    try:
        rows = amazon.get_orders_report(days_back=days_back)
        if not rows:
            log.warning("  No orders returned from report.")
            return 0

        # Deduplicate by (amazon_order_id, sku) — sum quantities for splits
        deduped = {}
        for row in rows:
            key = (row["amazon_order_id"], row["sku"])
            if key in deduped:
                deduped[key]["quantity"] += row["quantity"]
                deduped[key]["item_price"] += row["item_price"]
            else:
                deduped[key] = dict(row)
        deduped_rows = list(deduped.values())
        log.info(f"  Deduped: {len(rows)} → {len(deduped_rows)} rows")

        # Upsert in batches of 500 to avoid request size limits
        batch_size = 500
        for i in range(0, len(deduped_rows), batch_size):
            batch = deduped_rows[i:i + batch_size]
            supabase.table("orders").upsert(batch, on_conflict="amazon_order_id,sku").execute()
            log.info(f"  Batch {i//batch_size + 1}: {len(batch)} rows inserted")

        log.info(f"  ✅ Orders synced: {len(deduped_rows)} line items")
        return len(deduped_rows)

    except Exception as e:
        log.error(f"  ❌ Orders sync failed: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Sync Amazon data to Supabase")
    parser.add_argument("--inventory", action="store_true", help="Sync inventory only")
    parser.add_argument("--orders",    action="store_true", help="Sync orders only")
    parser.add_argument("--days",      type=int, default=90, help="Days of order history to pull (default: 90)")
    args = parser.parse_args()

    # Default: sync everything
    do_inventory = args.inventory or (not args.inventory and not args.orders)
    do_orders    = args.orders    or (not args.inventory and not args.orders)

    log.info("=" * 50)
    log.info(f"Sync started at {datetime.utcnow().isoformat()}")

    amazon   = AmazonClient()
    supabase = get_supabase()

    inv_count   = sync_inventory(amazon, supabase) if do_inventory else 0
    order_count = sync_orders(amazon, supabase, days_back=args.days) if do_orders else 0

    log.info(f"Sync complete — {inv_count} inventory SKUs, {order_count} orders")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
