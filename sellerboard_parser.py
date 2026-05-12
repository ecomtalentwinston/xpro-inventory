from datetime import date, timedelta

import pandas as pd

REQUIRED_COLUMNS = {"Product", "ASIN", "Units"}


def parse_sellerboard_report(file, report_days: int, end_date: date):
    """Parse a Sellerboard Products Dashboard Excel export.

    Returns (results, zero_unit_asins) where results is a list of dicts and
    zero_unit_asins is a list of ASINs that had 0 units sold.
    """
    df = pd.read_excel(file)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"File does not appear to be a Sellerboard Products report. "
            f"Missing columns: {', '.join(sorted(missing))}"
        )

    start_date = end_date - timedelta(days=report_days)

    # Deduplicate by ASIN, keeping highest units (same logic as business_report_parser)
    seen: dict = {}
    zero_unit_asins = []

    for _, row in df.iterrows():
        asin = str(row["ASIN"]).strip()

        # Product column appends "\nCOG: X / Price: Y" — keep only the first line
        product_raw = str(row["Product"]).strip()
        title = product_raw.split("\n")[0].strip()

        try:
            units_ordered = int(float(str(row["Units"]).replace(",", "").strip()))
        except (ValueError, TypeError):
            units_ordered = 0

        if units_ordered == 0:
            if asin not in seen:
                zero_unit_asins.append(asin)
            continue

        if asin not in seen or units_ordered > seen[asin]["units_ordered"]:
            seen[asin] = {
                "child_asin": asin,
                "parent_asin": asin,
                "title": title,
                "units_ordered": units_ordered,
                "daily_velocity": round(units_ordered / report_days, 4),
                "report_days": report_days,
                "start_date": start_date,
                "end_date": end_date,
            }

    return list(seen.values()), zero_unit_asins
