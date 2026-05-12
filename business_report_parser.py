from datetime import date, timedelta

import pandas as pd

REQUIRED_COLUMNS = {"(Child) ASIN", "(Parent) ASIN", "Title", "Units Ordered"}


def parse_business_report(file, report_days: int, end_date: date):
    """Parse an Amazon Business Report CSV and return sales data per ASIN.

    Returns (results, zero_unit_asins) where results is a list of dicts and
    zero_unit_asins is a list of child ASINs that had 0 units ordered.
    """
    df = pd.read_csv(file)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"File does not appear to be an Amazon Business Report. "
            f"Missing columns: {', '.join(sorted(missing))}"
        )

    start_date = end_date - timedelta(days=report_days)

    # Use dicts keyed by child_asin to deduplicate — Amazon reports occasionally
    # list the same child ASIN twice (e.g. under different parent ASINs).
    # Keep the row with the highest units_ordered.
    seen: dict = {}
    zero_unit_asins = []

    for _, row in df.iterrows():
        child_asin = str(row["(Child) ASIN"]).strip()
        parent_asin = str(row["(Parent) ASIN"]).strip()
        title = str(row["Title"]).strip()

        units_str = str(row["Units Ordered"]).replace(",", "").strip()
        try:
            units_ordered = int(units_str)
        except ValueError:
            units_ordered = 0

        if units_ordered == 0:
            if child_asin not in seen:
                zero_unit_asins.append(child_asin)
            continue

        if child_asin not in seen or units_ordered > seen[child_asin]["units_ordered"]:
            daily_velocity = round(units_ordered / report_days, 4)
            seen[child_asin] = {
                "child_asin": child_asin,
                "parent_asin": parent_asin,
                "title": title,
                "units_ordered": units_ordered,
                "daily_velocity": daily_velocity,
                "report_days": report_days,
                "start_date": start_date,
                "end_date": end_date,
            }

    return list(seen.values()), zero_unit_asins
