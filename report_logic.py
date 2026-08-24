from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd


VN_TZ = "Asia/Ho_Chi_Minh"
LA_TZ = "America/Los_Angeles"

MASTER_ALIASES = {
    "record_id": ["record id", "record_id", "_record_id"],
    "image": ["image", "image url", "image_url", "product image", "photo"],
    "asin": ["asin"],
    "sku": ["sku", "amz sku", "amz_sku"],
    "product_name": ["product name", "product", "title"],
    "product_type": ["product type", "type"],
    "store": ["amz store", "amazon store", "store"],
    "fulfill_by": ["fulfill by", "fulfillment", "fulfillment by"],
    "asin_manager": ["owners", "asin manager", "product owner", "owner", "managed by", "manage by", "manager"],
    "mrnd": ["mrnd idea", "mrnd", "is mrnd", "is_mrnd"],
    "listing_by": ["listing by", "listing_by"],
    "custom_by": ["custom by", "custom_by"],
    "custom_check_done": [
        "custom check done", "custom_check_done", "custom done", "custom done date",
        "custom check done date", "custom check done time", "custom check done at",
    ],
    "status": ["status"],
}

ORDER_ALIASES = {
    "order_date": ["order date", "date", "purchase date", "purchase-date", "purchase time", "purchase-time"],
    "order_id": ["order id", "amazon order id", "amazon-order-id"],
    "order_status": ["order status", "order-status", "status"],
    "item_status": ["item status", "item-status"],
    "fulfillment_channel": ["fulfillment channel", "fulfillment-channel"],
    "asin": ["asin"],
    "qty": ["qty", "quantity", "quantity purchased"],
    "item_price": ["item price", "product sales", "price"],
    "shipping": ["shipping", "shipping price"],
    "promotion": ["promotion", "promotion discount", "item promotion discount"],
    "ship_promotion": ["ship promotion discount", "shipping promotion discount"],
}


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def standardize_columns(df: pd.DataFrame, aliases: dict[str, list[str]]) -> pd.DataFrame:
    normalized = {normalize_header(column): column for column in df.columns}
    exact = {str(column).strip().lower(): column for column in df.columns}
    rename: dict[str, str] = {}
    for target, candidates in aliases.items():
        for candidate in candidates:
            original = exact.get(str(candidate).strip().lower()) or normalized.get(normalize_header(candidate))
            if original is not None:
                rename[original] = target
                break
        # Lark/Excel exports can append a field type or annotation to the
        # column name, for example "Custom Check Done (Date)". Keep this
        # fallback narrowly scoped so unrelated date fields are never used.
        if target == "custom_check_done" and target not in rename.values():
            for normalized_name, original in normalized.items():
                if normalized_name.startswith(("custom check done ", "custom done ")):
                    rename[original] = target
                    break
    return df.rename(columns=rename)


def normalize_asin(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.upper()


def display_store(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    mapping = {
        "wrappiness": "WR",
        "wr": "WR",
        "pawsionate": "PAW",
        "paw": "PAW",
    }
    return values.map(lambda value: mapping.get(value.lower(), value))


def parse_custom_done(series: pd.Series) -> pd.Series:
    """Parse CSV/Excel dates as Vietnam-local calendar values without double-localizing."""
    numeric = pd.to_numeric(series, errors="coerce")
    output = pd.Series(pd.NaT, index=series.index, dtype=f"datetime64[ns, {VN_TZ}]")
    epoch_ms = numeric.ge(10**11)
    epoch_seconds = numeric.ge(10**9) & numeric.lt(10**11)
    excel_serial = numeric.between(20_000, 80_000, inclusive="both")
    if epoch_ms.any():
        output.loc[epoch_ms] = pd.to_datetime(numeric.loc[epoch_ms], unit="ms", errors="coerce", utc=True).dt.tz_convert(VN_TZ)
    if epoch_seconds.any():
        output.loc[epoch_seconds] = pd.to_datetime(numeric.loc[epoch_seconds], unit="s", errors="coerce", utc=True).dt.tz_convert(VN_TZ)
    if excel_serial.any():
        parsed_excel = pd.to_datetime(
            numeric.loc[excel_serial], unit="D", origin="1899-12-30", errors="coerce"
        ).dt.tz_localize(VN_TZ, nonexistent="shift_forward", ambiguous="NaT")
        output.loc[excel_serial] = parsed_excel
    numeric_dates = epoch_ms | epoch_seconds | excel_serial
    text_mask = ~numeric_dates & series.notna() & series.astype(str).str.strip().ne("")
    if text_mask.any():
        # `format="mixed"` parses each cell independently. Lark/Excel exports
        # often mix date-only and date-time text in the same column.
        parsed = pd.to_datetime(series.loc[text_mask], errors="coerce", format="mixed")
        if getattr(parsed.dt, "tz", None) is None:
            parsed = parsed.dt.tz_localize(VN_TZ, nonexistent="shift_forward", ambiguous="NaT")
        else:
            parsed = parsed.dt.tz_convert(VN_TZ)
        output.loc[text_mask] = parsed
    return output


def clean_master(raw: pd.DataFrame, image_normalizer=None) -> pd.DataFrame:
    df = standardize_columns(raw.copy(), MASTER_ALIASES)
    if "asin" not in df:
        raise ValueError("Product Master thiếu cột ASIN.")
    for column in MASTER_ALIASES:
        if column not in df:
            df[column] = ""
    df["asin"] = normalize_asin(df["asin"])
    for column in ["record_id", "sku", "product_name", "product_type", "store", "fulfill_by", "asin_manager", "listing_by", "custom_by", "status"]:
        df[column] = df[column].fillna("").astype(str).str.strip()
    if image_normalizer:
        df["image"] = df["image"].map(image_normalizer)
    else:
        df["image"] = df["image"].fillna("").astype(str)
    df["fulfill_by"] = df["fulfill_by"].str.upper()
    df = df[df["asin"].ne("") & ~df["fulfill_by"].eq("FBA")].drop_duplicates("asin", keep="last")
    mrnd_text = df["mrnd"].fillna("").astype(str).str.strip().str.lower()
    df["mrnd"] = ~mrnd_text.isin(["", "no", "false", "0", "0.0", "none", "nan", "n", "non-mrnd"])
    df["store_display"] = display_store(df["store"])
    df["custom_check_done"] = parse_custom_done(df["custom_check_done"])
    df["status"] = df["status"].replace("", "Active")
    return df[list(MASTER_ALIASES) + ["store_display"]]


def clean_orders(raw: pd.DataFrame) -> pd.DataFrame:
    df = standardize_columns(raw.copy(), ORDER_ALIASES)
    required = ["order_date", "order_id", "asin"]
    missing = [column for column in required if column not in df]
    if missing:
        raise ValueError("Order Report thiếu cột: " + ", ".join(missing))
    for column in ORDER_ALIASES:
        if column not in df:
            df[column] = 0 if column in {"qty", "item_price", "shipping", "promotion", "ship_promotion"} else ""
    df["asin"] = normalize_asin(df["asin"])
    df["order_id"] = df["order_id"].fillna("").astype(str).str.strip()
    # Explicitly preserve an aware instant through UTC -> Los Angeles -> Vietnam.
    df["order_date"] = (
        pd.to_datetime(df["order_date"], errors="coerce", utc=True)
        .dt.tz_convert(LA_TZ)
        .dt.tz_convert(VN_TZ)
    )
    for column in ["qty", "item_price", "shipping", "promotion", "ship_promotion"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df["net_revenue"] = df["item_price"] + df["shipping"]
    order_status = df["order_status"].fillna("").astype(str).str.strip().str.lower()
    item_status = df["item_status"].fillna("").astype(str).str.strip().str.lower()
    cancelled = order_status.isin(["cancelled", "canceled"]) | item_status.isin(["cancelled", "canceled"])
    fulfillment = df["fulfillment_channel"].fillna("").astype(str).str.strip().str.lower()
    fbm = fulfillment.eq("") | fulfillment.isin(["merchant", "fbm"])
    result = df.loc[~cancelled & fbm].dropna(subset=["order_date"])[list(ORDER_ALIASES) + ["net_revenue"]].copy()
    fingerprint_columns = ["order_date", "order_id", "asin", "qty", "item_price", "shipping", "promotion", "ship_promotion"]
    result["row_hash"] = result[fingerprint_columns].astype(str).agg("|".join, axis=1).map(lambda value: hashlib.sha256(value.encode()).hexdigest())
    return result.drop_duplicates("row_hash")


def vn_bounds(start_date, end_date) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(start_date).tz_localize(VN_TZ)
    end_exclusive = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize(VN_TZ)
    return start, end_exclusive


def filter_dates(df: pd.DataFrame, column: str, start_date, end_date) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    start, end_exclusive = vn_bounds(start_date, end_date)
    return df[df[column].ge(start) & df[column].lt(end_exclusive)].copy()


def add_week_bucket(df: pd.DataFrame, date_column: str) -> pd.DataFrame:
    result = df.copy()
    local_naive = result[date_column].dt.tz_convert(VN_TZ).dt.tz_localize(None)
    result["week_start"] = local_naive.dt.normalize() - pd.to_timedelta(local_naive.dt.weekday, unit="D")
    result["week_end"] = result["week_start"] + pd.Timedelta(days=6)
    result["week_label"] = result["week_start"].dt.strftime("%d/%m/%Y") + "-" + result["week_end"].dt.strftime("%d/%m/%Y")
    return result


def manager_kpis(master_scope: pd.DataFrame, period_orders: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    columns = [
        "ASIN Manager", "Record >10 Orders", "Record >$1K", "Record >$3K",
        "Record >$5K", "Record >$10K", "New ASIN Sold", "New MRnD Sold",
        "New Non-MRnD Sold", "New ASIN Revenue", "New MRnD Revenue",
        "New Non-MRnD Revenue", "Sold Rate", "Total Revenue",
    ]
    if master_scope.empty:
        return pd.DataFrame(columns=columns)
    order_agg = period_orders.groupby("asin", as_index=False).agg(
        revenue=("net_revenue", "sum"), orders=("order_id", "nunique")
    ) if not period_orders.empty else pd.DataFrame(columns=["asin", "revenue", "orders"])
    portfolio = master_scope[["asin", "record_id", "asin_manager", "custom_check_done", "mrnd"]].drop_duplicates("asin").copy()
    portfolio["record_key"] = portfolio["record_id"].where(portfolio["record_id"].ne(""), "ASIN:" + portfolio["asin"])
    portfolio = portfolio.merge(order_agg, on="asin", how="left")
    portfolio["revenue"] = pd.to_numeric(portfolio["revenue"], errors="coerce").fillna(0.0)
    portfolio["orders"] = pd.to_numeric(portfolio["orders"], errors="coerce").fillna(0).astype(int)
    start, end_exclusive = vn_bounds(start_date, end_date)
    portfolio["is_new"] = portfolio["custom_check_done"].ge(start) & portfolio["custom_check_done"].lt(end_exclusive)
    rows = []
    for manager, group in portfolio.groupby("asin_manager", dropna=False):
        # Count each Order ID once per Record ID, even when several ASINs in that
        # record occur in the same Amazon order.
        manager_orders = period_orders[period_orders["asin"].isin(set(group["asin"]))].merge(
            group[["asin", "record_key"]], on="asin", how="inner"
        )
        record = manager_orders.groupby("record_key", as_index=False).agg(
            revenue=("net_revenue", "sum"), orders=("order_id", "nunique")
        ) if not manager_orders.empty else pd.DataFrame(columns=["record_key", "revenue", "orders"])
        new = group[group["is_new"]]
        sold_new = new[new["orders"].gt(0)]
        sold_new_mrnd = sold_new[sold_new["mrnd"]]
        sold_new_non_mrnd = sold_new[~sold_new["mrnd"]]
        denominator = new["asin"].nunique()
        rows.append({
            "ASIN Manager": manager or "Chưa xác định",
            "Record >10 Orders": int(record["orders"].gt(10).sum()),
            "Record >$1K": int(record["revenue"].gt(1000).sum()),
            "Record >$3K": int(record["revenue"].gt(3000).sum()),
            "Record >$5K": int(record["revenue"].gt(5000).sum()),
            "Record >$10K": int(record["revenue"].gt(10000).sum()),
            "New ASIN Sold": sold_new["asin"].nunique(),
            "New MRnD Sold": sold_new_mrnd["asin"].nunique(),
            "New Non-MRnD Sold": sold_new_non_mrnd["asin"].nunique(),
            "New ASIN Revenue": sold_new["revenue"].sum(),
            "New MRnD Revenue": sold_new_mrnd["revenue"].sum(),
            "New Non-MRnD Revenue": sold_new_non_mrnd["revenue"].sum(),
            "Sold Rate": sold_new["asin"].nunique() / denominator if denominator else 0.0,
            "Total Revenue": group["revenue"].sum(),
        })
    return pd.DataFrame(rows, columns=columns).sort_values("Total Revenue", ascending=False)


def personnel_listing_table(scope: pd.DataFrame, person_column: str) -> pd.DataFrame:
    columns = ["Nhân sự", "Total Custom Done", "MRnD", "Non-MRnD", "MRnD Rate"]
    if scope.empty:
        return pd.DataFrame(columns=columns)
    work = scope[["asin", person_column, "mrnd"]].drop_duplicates("asin").copy()
    work[person_column] = work[person_column].replace("", "Chưa xác định")
    total = work.groupby(person_column)["asin"].nunique().rename("Total Custom Done")
    mrnd = work[work["mrnd"]].groupby(person_column)["asin"].nunique().rename("MRnD")
    non = work[~work["mrnd"]].groupby(person_column)["asin"].nunique().rename("Non-MRnD")
    result = pd.concat([total, mrnd, non], axis=1).fillna(0).reset_index().rename(columns={person_column: "Nhân sự"})
    result[["Total Custom Done", "MRnD", "Non-MRnD"]] = result[["Total Custom Done", "MRnD", "Non-MRnD"]].astype(int)
    result["MRnD Rate"] = result["MRnD"].div(result["Total Custom Done"].where(result["Total Custom Done"].ne(0))).fillna(0)
    return result[columns].sort_values("Total Custom Done", ascending=False)

