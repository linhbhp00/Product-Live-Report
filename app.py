from __future__ import annotations

from io import BytesIO
from pathlib import Path
import os
import re

import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="Product Live Report", page_icon="📈", layout="wide")

ROOT = Path(__file__).parent
LARK_BASE_URL = "https://everlastify.jp.larksuite.com/base/RXnkbQ0NXaPKanshOEfjtNwjp7k?table=tblgsIV71tjUvLlB&view=vewuAjvYoo"
LARK_APP_TOKEN = "RXnkbQ0NXaPKanshOEfjtNwjp7k"
LARK_TABLE_ID = "tblgsIV71tjUvLlB"
LARK_VIEW_ID = "vewuAjvYoo"

MASTER_ALIASES = {
    "asin": ["asin"],
    "sku": ["sku", "amz sku", "amz_sku"],
    "product_name": ["product name", "product", "title"],
    "product_type": ["product type", "type"],
    "asin_manager": ["owners", "asin manager", "product owner", "owner", "managed by", "manager"],
    "mrnd": ["mrnd idea", "mrnd", "is mrnd", "is_mrnd"],
    "listing_by": ["listing by", "listing_by"],
    "custom_by": ["custom by", "custom_by"],
    "status": ["status"],
}

ORDER_ALIASES = {
    "order_date": ["order date", "date", "purchase date", "purchase-date"],
    "order_id": ["order id", "amazon order id", "amazon-order-id"],
    "order_status": ["order status", "order-status", "status"],
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
    rename = {}
    for target, candidates in aliases.items():
        for candidate in candidates:
            original = normalized.get(normalize_header(candidate))
            if original is not None:
                rename[original] = target
                break
    return df.rename(columns=rename)


def read_upload(file) -> pd.DataFrame:
    suffix = Path(file.name).suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file)
    if suffix in {".txt", ".tsv"}:
        return pd.read_csv(file, sep="\t")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file)
    raise ValueError("Chỉ hỗ trợ CSV, TXT/TSV, XLSX hoặc XLS.")


@st.cache_data
def read_sample(name: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / name)


def clean_master(raw: pd.DataFrame) -> pd.DataFrame:
    df = standardize_columns(raw.copy(), MASTER_ALIASES)
    if "asin" not in df:
        raise ValueError("Product Master thiếu cột ASIN.")
    for column in MASTER_ALIASES:
        if column not in df:
            df[column] = ""
    df["asin"] = df["asin"].fillna("").astype(str).str.strip().str.upper()
    df = df[df["asin"].ne("")].drop_duplicates("asin", keep="last")
    mrnd_text = df["mrnd"].fillna("").astype(str).str.strip().str.lower()
    df["mrnd"] = ~mrnd_text.isin(["", "no", "false", "0", "none", "nan", "n"])
    df["status"] = df["status"].fillna("Active").replace("", "Active")
    return df[list(MASTER_ALIASES)]


def clean_orders(raw: pd.DataFrame) -> pd.DataFrame:
    df = standardize_columns(raw.copy(), ORDER_ALIASES)
    required = ["order_date", "order_id", "asin"]
    missing = [column for column in required if column not in df]
    if missing:
        raise ValueError("Order Report thiếu cột: " + ", ".join(missing))
    for column in ORDER_ALIASES:
        if column not in df:
            df[column] = 0 if column in {"qty", "item_price", "shipping", "promotion", "ship_promotion"} else ""
    df["asin"] = df["asin"].fillna("").astype(str).str.strip().str.upper()
    df["order_id"] = df["order_id"].fillna("").astype(str).str.strip()
    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    for column in ["qty", "item_price", "shipping", "promotion", "ship_promotion"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df["net_revenue"] = (
        df["item_price"]
        + df["shipping"]
        - df["promotion"].abs()
        - df["ship_promotion"].abs()
    )
    cancelled = df["order_status"].fillna("").astype(str).str.strip().str.lower().eq("cancelled")
    return df.loc[~cancelled].dropna(subset=["order_date"])


def load_default_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    return clean_master(read_sample("product_master.csv")), clean_orders(read_sample("order_report.csv"))


def lark_settings() -> dict[str, str]:
    try:
        section = dict(st.secrets.get("lark", {}))
    except Exception:
        section = {}
    return {
        "app_id": str(section.get("app_id") or os.getenv("LARK_APP_ID", "")),
        "app_secret": str(section.get("app_secret") or os.getenv("LARK_APP_SECRET", "")),
        "app_token": str(section.get("app_token") or LARK_APP_TOKEN),
        "table_id": str(section.get("table_id") or LARK_TABLE_ID),
        "view_id": str(section.get("view_id") or LARK_VIEW_ID),
    }


def flatten_lark_value(value):
    if isinstance(value, list):
        parts = [flatten_lark_value(item) for item in value]
        return ", ".join(str(item) for item in parts if str(item).strip())
    if isinstance(value, dict):
        for key in ("name", "text", "display_name", "en_name", "link"):
            if value.get(key):
                return value[key]
        return ", ".join(str(item) for item in value.values() if item not in (None, ""))
    return "" if value is None else value


@st.cache_data(ttl=600, show_spinner=False)
def fetch_lark_master(app_id: str, app_secret: str, app_token: str, table_id: str, view_id: str) -> pd.DataFrame:
    token_response = requests.post(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=20,
    )
    token_response.raise_for_status()
    token_payload = token_response.json()
    token = token_payload.get("tenant_access_token")
    if not token:
        raise ValueError(token_payload.get("msg", "Không lấy được Lark access token."))

    records, page_token = [], None
    while True:
        params = {"page_size": 500, "view_id": view_id}
        if page_token:
            params["page_token"] = page_token
        response = requests.get(
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(payload.get("msg", "Không đọc được Lark Base."))
        data = payload.get("data", {})
        records.extend(item.get("fields", {}) for item in data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")

    normalized = [{key: flatten_lark_value(value) for key, value in record.items()} for record in records]
    return clean_master(pd.DataFrame(normalized))


def initialize_state() -> None:
    if "product_master" not in st.session_state:
        sample_master, orders = load_default_data()
        settings = lark_settings()
        if settings["app_id"] and settings["app_secret"]:
            try:
                master = fetch_lark_master(**settings)
                st.session_state.lark_connected = True
                st.session_state.master_source = f"Lark Base · {len(master):,} ASIN"
            except Exception as exc:
                master = sample_master
                st.session_state.lark_connected = False
                st.session_state.master_source = f"Lark chưa kết nối · {exc}"
        else:
            master = sample_master
            st.session_state.lark_connected = False
            st.session_state.master_source = "Lark chưa cấu hình · đang dùng dữ liệu mẫu"
        st.session_state.product_master = master
        st.session_state.orders = orders
        st.session_state.data_source = "Dữ liệu mẫu"


def money(value: float) -> str:
    return f"${value:,.2f}"


def apply_import(master_file, order_file) -> None:
    if order_file is None:
        st.error("Vui lòng chọn Order Report.")
        return
    try:
        if master_file is not None:
            master = clean_master(read_upload(master_file))
            st.session_state.product_master = master
            st.session_state.lark_connected = False
            st.session_state.master_source = f"Product Master upload · {len(master):,} ASIN"
        orders = clean_orders(read_upload(order_file))
        st.session_state.orders = orders
        st.session_state.data_source = order_file.name
        master_note = f" và {len(st.session_state.product_master):,} ASIN" if master_file is not None else ""
        st.success(f"Đã import {len(orders):,} transaction{master_note}.")
    except Exception as exc:
        st.error(str(exc))


initialize_state()

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@700;800&display=swap');
    :root { --deep:#143f32; --green:#1b6b50; --muted:#718078; --line:#e4eae6; --paper:#ffffff; }
    .stApp { background:#f4f6f4; color:#17201d; font-family:'DM Sans',sans-serif; }
    [data-testid="stHeader"] { background:transparent; }
    [data-testid="stAppViewContainer"] > .main .block-container { max-width:1480px; padding:1.5rem 2.4rem 4rem; }
    .appbar { background:var(--deep); color:white; margin:-1.5rem -2.4rem 2rem; padding:17px 2.4rem; display:flex; align-items:center; justify-content:space-between; }
    .brand { display:flex; align-items:center; gap:11px; font-family:Manrope,sans-serif; font-weight:800; }
    .brand-badge { display:grid; place-items:center; width:32px; height:32px; border-radius:9px; color:#143f32; background:#cde96d; }
    .sync { font-size:12px; color:#cfddd8; } .sync b { color:#79d8a8; }
    .hero { display:flex; justify-content:space-between; align-items:end; margin-bottom:1.3rem; }
    .eyebrow { color:var(--green); font-size:11px; font-weight:700; letter-spacing:1.6px; }
    .hero h1 { font:800 32px/1.2 Manrope,sans-serif; margin:7px 0 5px; letter-spacing:-1px; }
    .hero p { color:var(--muted); margin:0; font-size:14px; }
    [data-testid="stMetric"] { background:white; border:1px solid var(--line); border-radius:10px; padding:15px 18px; min-height:112px; box-shadow:0 1px 2px rgba(20,45,36,.03); }
    [data-testid="stMetricLabel"] { color:#68776f; font-size:12px; font-weight:600; }
    [data-testid="stMetricValue"] { font-family:Manrope,sans-serif; font-size:25px; letter-spacing:-.7px; }
    [data-testid="stMetricDelta"] { font-size:11px; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line); border-radius:11px; background:white; box-shadow:0 10px 30px rgba(20,45,36,.05); }
    .section-title { font:700 17px Manrope,sans-serif; margin:0; }
    .section-sub { color:#8a9690; font-size:12px; margin:4px 0 14px; }
    .quality { display:flex; gap:18px; font-size:11px; color:#78867f; padding:6px 0 0; }
    .quality b { color:#2d493d; }
    .quality .ok::before,.quality .warn::before { content:''; width:7px; height:7px; display:inline-block; border-radius:50%; margin-right:6px; }
    .quality .ok::before { background:#53ad85; } .quality .warn::before { background:#e0ad63; }
    [data-testid="stDataFrame"] { border:1px solid #edf0ee; border-radius:8px; }
    .stButton button[kind="primary"] { background:var(--green); border-color:var(--green); font-weight:700; }
    .stButton button { border-radius:8px; }
    hr { border-color:var(--line) !important; }
    @media(max-width:700px){ [data-testid="stAppViewContainer"] > .main .block-container{padding:1rem}.appbar{margin:-1rem -1rem 1.5rem;padding:14px 1rem}.sync{display:none}.hero h1{font-size:27px} }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="appbar"><div class="brand"><span class="brand-badge">P</span>Product Live Report</div>
    <div class="sync"><b>●</b>&nbsp; {st.session_state.master_source}</div></div>
    <div class="hero"><div><div class="eyebrow">PERFORMANCE OVERVIEW</div><h1>Sales performance</h1>
    <p>Order Report được map với Product Master bằng ASIN.</p></div></div>
    """,
    unsafe_allow_html=True,
)

with st.expander("↑  Import dữ liệu", expanded=False):
    left, right = st.columns(2)
    with left:
        master_upload = st.file_uploader(
            "Product Master từ Lark Base",
            type=["csv", "xlsx", "xls"],
            help="File export của bảng TOTAL ASINs / view All",
        )
        st.caption("Cần: ASIN. Tự nhận AMZ SKU, Product Name, Product Type, Managed By, MRnD Idea, Listing By và Custom By.")
    with right:
        order_upload = st.file_uploader(
            "Order Report",
            type=["txt", "tsv", "csv", "xlsx", "xls"],
            help="Amazon Order Report theo ngày",
        )
        st.caption("Hỗ trợ trực tiếp TXT tab-delimited của Amazon và tự loại đơn Cancelled.")
    if st.button("Kiểm tra & import", type="primary", use_container_width=True):
        apply_import(master_upload, order_upload)

settings = lark_settings()
if settings["app_id"] and settings["app_secret"]:
    if st.button("↻  Đồng bộ lại Product Master từ Lark"):
        try:
            fetch_lark_master.clear()
            synced_master = fetch_lark_master(**settings)
            st.session_state.product_master = synced_master
            st.session_state.lark_connected = True
            st.session_state.master_source = f"Lark Base · {len(synced_master):,} ASIN"
            st.success(f"Đã đồng bộ {len(synced_master):,} ASIN từ TOTAL ASINs.")
            st.rerun()
        except Exception as exc:
            st.error(f"Không thể đồng bộ Lark: {exc}")
else:
    st.info("App đã cố định Product Master vào bảng TOTAL ASINs. Hãy cấu hình LARK_APP_ID và LARK_APP_SECRET trong Streamlit Secrets để bật đồng bộ trực tiếp.")

master = st.session_state.product_master.copy()
orders = st.session_state.orders.copy()
known_asins = set(master["asin"])
orders["mapped"] = orders["asin"].isin(known_asins)
mapped_orders = orders[orders["mapped"]].copy()

if mapped_orders.empty:
    st.warning("Không có transaction nào map được với Product Master.")
    st.stop()

minimum, maximum = mapped_orders["order_date"].min().date(), mapped_orders["order_date"].max().date()

with st.container(border=True):
    st.markdown('<p class="section-title">Bộ lọc báo cáo</p><p class="section-sub">KPI và bảng được tính lại từ transaction gốc.</p>', unsafe_allow_html=True)
    f1, f2, f3, f4, f5 = st.columns([1.45, 1.1, 1, 1, .8])
    with f1:
        query = st.text_input("Tìm kiếm", placeholder="SKU, ASIN hoặc Product Name")
    with f2:
        date_range = st.date_input("Khoảng thời gian", value=(minimum, maximum), min_value=minimum, max_value=maximum)
    with f3:
        type_options = sorted(master["product_type"].dropna().astype(str).loc[lambda x: x.ne("")].unique())
        selected_types = st.multiselect("Product Type", type_options, placeholder="Tất cả loại")
    with f4:
        manager_options = sorted(master["asin_manager"].dropna().astype(str).loc[lambda x: x.ne("")].unique())
        selected_managers = st.multiselect("ASIN Manager", manager_options, placeholder="Tất cả quản lý")
    with f5:
        mrnd_filter = st.selectbox("MRnD", ["Tất cả", "MRnD", "Non-MRnD"])

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
else:
    start_date = end_date = pd.Timestamp(date_range)

period_orders = mapped_orders[mapped_orders["order_date"].between(start_date, end_date + pd.Timedelta(days=1), inclusive="left")]
summary = (
    period_orders.groupby("asin", as_index=False)
    .agg(net_revenue=("net_revenue", "sum"), orders=("order_id", "nunique"), qty=("qty", "sum"))
    .merge(master, on="asin", how="left")
)

if query:
    needle = query.strip().lower()
    summary = summary[
        summary[["sku", "asin", "product_name"]].fillna("").astype(str).apply(
            lambda column: column.str.lower().str.contains(needle, regex=False)
        ).any(axis=1)
    ]
if selected_types:
    summary = summary[summary["product_type"].isin(selected_types)]
if selected_managers:
    summary = summary[summary["asin_manager"].isin(selected_managers)]
if mrnd_filter != "Tất cả":
    summary = summary[summary["mrnd"].eq(mrnd_filter == "MRnD")]

total_asin = master.loc[~master["status"].astype(str).str.lower().eq("inactive"), "asin"].nunique()
asin_sold = summary["asin"].nunique()
sale_rate = asin_sold / total_asin if total_asin else 0

k1, k2, k3, k4, k5 = st.columns([1.25, 1, 1, 1, 1])
k1.metric("Net Revenue", money(summary["net_revenue"].sum()), help="Item Price + Shipping - Item Promotion - Shipping Promotion")
k2.metric("Orders", f"{summary['orders'].sum():,.0f}")
k3.metric("ASIN Sold", f"{asin_sold:,}")
k4.metric("Total ASIN", f"{total_asin:,}")
k5.metric("Sale Rate", f"{sale_rate:.1%}")

st.write("")
with st.container(border=True):
    h1, h2, h3 = st.columns([2, 1, .75])
    with h1:
        st.markdown('<p class="section-title">Product performance</p>', unsafe_allow_html=True)
        st.markdown(f'<p class="section-sub">Hiển thị {len(summary):,} sản phẩm đã map ASIN</p>', unsafe_allow_html=True)
    with h2:
        sort_column = st.selectbox("Sắp xếp theo", ["Net Revenue", "Orders", "Qty", "Product Name", "Product Type", "ASIN Manager"], label_visibility="collapsed")
    with h3:
        direction = st.selectbox("Thứ tự", ["Giảm dần", "Tăng dần"], label_visibility="collapsed")

    sort_map = {
        "Net Revenue": "net_revenue", "Orders": "orders", "Qty": "qty", "Product Name": "product_name",
        "Product Type": "product_type", "ASIN Manager": "asin_manager",
    }
    summary = summary.sort_values(sort_map[sort_column], ascending=direction == "Tăng dần", na_position="last")
    display = summary[["product_name", "sku", "asin", "product_type", "asin_manager", "mrnd", "listing_by", "custom_by", "net_revenue", "orders", "qty"]].copy()
    display["mrnd"] = display["mrnd"].map({True: "MRnD", False: "Non-MRnD"})
    display.columns = ["Product Name", "SKU", "ASIN", "Product Type", "ASIN Manager", "MRnD", "Listing By", "Custom By", "Net Revenue", "Orders", "Qty"]
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        height=min(620, 48 + max(len(display), 5) * 36),
        column_config={"Net Revenue": st.column_config.NumberColumn(format="$%.2f"), "Orders": st.column_config.NumberColumn(format="%d"), "Qty": st.column_config.NumberColumn(format="%.0f")},
    )
    mapped_count = int(orders["mapped"].sum())
    unmapped_count = int((~orders["mapped"]).sum())
    st.markdown(f'<div class="quality"><span class="ok">Mapped: <b>{mapped_count:,}</b></span><span class="warn">Chưa map: <b>{unmapped_count:,}</b></span><span>Mapping rate: <b>{mapped_count / len(orders):.1%}</b></span></div>', unsafe_allow_html=True)

    export = display.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⇩  Xuất CSV", data=export, file_name="product-live-report.csv", mime="text/csv")

with st.expander("Data model & cohort roadmap"):
    st.markdown(
        """
        **Product Master:** upload file export của bảng `TOTAL ASINs` / view `All`, hoặc đồng bộ API khi được cấp quyền. `Managed By → ASIN Manager`, `MRnD Idea → MRnD`.

        **Order Report:** chỉ lưu transaction theo ngày. `Net Revenue = Item Price + Shipping - Item Promotion - Shipping Promotion`; đơn `Cancelled` được loại.
        **Cohort D7/D14/D30:** thêm `Live Date` vào Product Master, tính tuổi listing từ `Order Date - Live Date`, rồi nhóm doanh thu theo ngày tuổi.
        """
    )
