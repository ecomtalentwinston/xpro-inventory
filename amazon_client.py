import csv
import gzip
import io
import logging
import time
import requests
from datetime import datetime, timedelta
from config import (
    AMAZON_CLIENT_ID, AMAZON_CLIENT_SECRET,
    AMAZON_REFRESH_TOKEN, AMAZON_MARKETPLACE_ID,
    AMAZON_TOKEN_URL, AMAZON_API_BASE
)

logging.basicConfig(
    filename="logs/sync.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

class AmazonClient:
    def __init__(self):
        self._access_token = None
        self._token_expiry = None

    def _get_access_token(self):
        if self._access_token and datetime.utcnow() < self._token_expiry:
            return self._access_token
        resp = requests.post(AMAZON_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": AMAZON_REFRESH_TOKEN,
            "client_id": AMAZON_CLIENT_ID,
            "client_secret": AMAZON_CLIENT_SECRET,
        })
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600) - 60)
        return self._access_token

    def _headers(self):
        return {
            "x-amz-access-token": self._get_access_token(),
            "Content-Type": "application/json",
        }

    def test_connection(self):
        try:
            resp = requests.get(
                f"{AMAZON_API_BASE}/sellers/v1/marketplaceParticipations",
                headers=self._headers()
            )
            resp.raise_for_status()
            marketplaces = resp.json().get("payload", [])
            print("✅ Amazon SP-API connection successful!")
            for m in marketplaces:
                mp = m.get("marketplace", {})
                print(f"   Marketplace: {mp.get('name')} ({mp.get('id')})")
            return True
        except Exception as e:
            print(f"❌ Amazon SP-API connection failed: {e}")
            logging.error(f"Amazon connection test failed: {e}")
            return False

    # ------------------------------------------------------------------
    # INVENTORY via Reports API (GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA)
    # ------------------------------------------------------------------
    def _request_report(self, report_type):
        """Submit a report request and return the reportId."""
        resp = requests.post(
            f"{AMAZON_API_BASE}/reports/2021-06-30/reports",
            headers=self._headers(),
            json={
                "reportType": report_type,
                "marketplaceIds": [AMAZON_MARKETPLACE_ID],
            }
        )
        resp.raise_for_status()
        return resp.json().get("reportId")

    def _wait_for_report(self, report_id, max_wait=120):
        """Poll until report is DONE, return reportDocumentId."""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            resp = requests.get(
                f"{AMAZON_API_BASE}/reports/2021-06-30/reports/{report_id}",
                headers=self._headers()
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("processingStatus")
            if status == "DONE":
                return data.get("reportDocumentId")
            if status in ("CANCELLED", "FATAL"):
                raise Exception(f"Report {report_id} failed with status: {status}")
            time.sleep(5)
        raise TimeoutError(f"Report {report_id} did not complete within {max_wait}s")

    def _download_report(self, document_id):
        """Download and return report content as a string."""
        resp = requests.get(
            f"{AMAZON_API_BASE}/reports/2021-06-30/documents/{document_id}",
            headers=self._headers()
        )
        resp.raise_for_status()
        doc = resp.json()
        url = doc.get("url")
        compression = doc.get("compressionAlgorithm", "")

        raw = requests.get(url)
        raw.raise_for_status()

        if compression == "GZIP":
            return gzip.decompress(raw.content).decode("utf-8")
        return raw.content.decode("utf-8")

    def get_inventory(self):
        """
        Fetch FBA inventory via Reports API.
        Returns list of dicts with SKU-level inventory data.
        """
        logging.info("Requesting FBA inventory report...")
        report_id = self._request_report("GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA")
        logging.info(f"Report requested: {report_id} — waiting for completion...")
        print(f"  Report requested ({report_id}), waiting up to 2 min...")

        doc_id = self._wait_for_report(report_id, max_wait=120)
        content = self._download_report(doc_id)

        # Parse TSV
        reader = csv.DictReader(io.StringIO(content), delimiter="\t")
        items = []
        for row in reader:
            items.append({
                "sku":           row.get("seller-sku", "").strip(),
                "asin":          row.get("asin", "").strip(),
                "product_name":  row.get("product-name", "").strip(),
                "condition":     row.get("condition", "NewItem").strip(),
                "fba_available": int(row.get("afn-fulfillable-quantity", 0) or 0),
                "fba_reserved":  int(row.get("afn-reserved-quantity", 0) or 0),
                "fba_inbound":   int(row.get("afn-inbound-shipped-quantity", 0) or 0),
                "fc_processing": int(row.get("afn-inbound-receiving-quantity", 0) or 0),
                "awd_quantity":  0,  # pulled separately via AWD API
            })
        logging.info(f"Inventory report parsed: {len(items)} SKUs")
        return items

    # ------------------------------------------------------------------
    # ORDERS
    # ------------------------------------------------------------------
    def get_awd_inventory(self):
        """Fetch AWD inventory directly via AWD API."""
        try:
            resp = requests.get(
                f"{AMAZON_API_BASE}/awd/2024-05-09/inventory",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("inventory", [])
        except Exception as e:
            logging.error(f"get_awd_inventory failed: {e}")
            raise

    def get_orders_report(self, days_back=90):
        """
        Pull flat file orders reports in 30-day chunks (API limit).
        Returns combined list of SKU-level rows for the full date range.
        """
        all_rows = []
        chunk_size = 30
        now = datetime.utcnow()

        # Split into 30-day windows, newest first
        periods = []
        for offset in range(0, days_back, chunk_size):
            end = now - timedelta(days=offset)
            start = now - timedelta(days=min(offset + chunk_size, days_back))
            periods.append((start, end))

        for i, (start, end) in enumerate(periods):
            start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_str   = end.strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"  Chunk {i+1}/{len(periods)}: {start_str[:10]} → {end_str[:10]}")
            logging.info(f"Requesting orders chunk {i+1}: {start_str} to {end_str}")

            report_id = self._request_report_with_dates(
                "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
                start_str, end_str
            )
            doc_id = self._wait_for_report(report_id, max_wait=180)
            content = self._download_report(doc_id)

            reader = csv.DictReader(io.StringIO(content), delimiter="\t")
            chunk_rows = []
            for row in reader:
                status = row.get("order-status", "").strip()
                if status in ("Cancelled", "Pending"):
                    continue
                sku = row.get("sku", "").strip()
                if not sku:
                    continue
                chunk_rows.append({
                    "amazon_order_id":     row.get("amazon-order-id", "").strip(),
                    "sku":                 sku,
                    "asin":                row.get("asin", "").strip(),
                    "product_name":        row.get("product-name", "").strip(),
                    "quantity":            int(row.get("quantity", 1) or 1),
                    "item_price":          float(row.get("item-price", 0) or 0),
                    "currency":            row.get("currency", "USD").strip(),
                    "order_status":        status,
                    "fulfillment_channel": row.get("sales-channel", "").strip(),
                    "purchase_date":       row.get("purchase-date", "").strip(),
                    "last_updated_date":   row.get("last-updated-date", "").strip(),
                })
            print(f"    → {len(chunk_rows)} line items")
            all_rows.extend(chunk_rows)

            if i < len(periods) - 1:
                time.sleep(2)  # brief pause between report requests

        logging.info(f"Orders report total: {len(all_rows)} line items across {len(periods)} chunks")
        return all_rows

    def _request_report_with_dates(self, report_type, start_date, end_date):
        """Submit a report request with date range."""
        resp = requests.post(
            f"{AMAZON_API_BASE}/reports/2021-06-30/reports",
            headers=self._headers(),
            json={
                "reportType": report_type,
                "marketplaceIds": [AMAZON_MARKETPLACE_ID],
                "dataStartTime": start_date,
                "dataEndTime": end_date,
            }
        )
        resp.raise_for_status()
        return resp.json().get("reportId")


if __name__ == "__main__":
    client = AmazonClient()
    client.test_connection()
