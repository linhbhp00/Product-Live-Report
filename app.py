from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import hmac
import os

import pandas as pd
import streamlit as st

from charts import double_donut, listing_weekly_chart, sales_weekly_chart
from report_logic import VN_TZ, clean_master, clean_orders, filter_dates, manager_kpis, personnel_listing_table
from storage import (
    append_orders, create_storage, delete_batch, import_history, initialize_database,
    load_master, load_orders, master_import_history, replace_master,
)

st.set_page_config(page_title="Product Live Report", page_icon="📈", layout="wide")
ROOT = Path(__file__).parent
STORAGE_SCHEMA_VERSION = 2


def secrets(name: str) -> dict:
    try:
        return dict(st.secrets.get(name, {}))
    except Exception:
        return {}


def read_upload(file) -> pd.DataFrame:
    suffix, payload = Path(file.name).suffix.lower(), BytesIO(file.getvalue())
    if suffix == ".csv":
        return pd.read_csv(payload)
    if suffix in {".txt", ".tsv"}:
        return pd.read_csv(payload, sep="\t")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(payload)
    raise ValueError(f"{file.name}: định dạng không được hỗ trợ.")


def db_url() -> str:
    value = str(secrets("database").get("url") or os.getenv("DATABASE_URL", ""))
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+psycopg2://", 1)
    if value.startswith("postgresql://") and "+psycopg2" not in value:
        return value.replace("postgresql://", "postgresql+psycopg2://", 1)
    return value


@st.cache_resource
def get_storage(url: str, schema_version: int):
    # schema_version is intentionally part of the cache key. Increment it when
    # a deployment adds tables so Streamlit cannot reuse a pre-migration engine.
    return create_storage(url, ROOT)


def valid_admin_password(value: str) -> bool:
    section = secrets("admin")
    expected_hash = str(section.get("password_sha256") or "")
    if expected_hash:
        return hmac.compare_digest(hashlib.sha256(value.encode()).hexdigest(), expected_hash)
    expected = str(section.get("password") or os.getenv("ADMIN_PASSWORD", ""))
    return bool(expected) and hmac.compare_digest(value, expected)


def admin_login() -> bool:
    st.sidebar.markdown("### Quyền truy cập")
    if st.session_state.get("is_admin"):
        st.sidebar.success("Creator / Admin")
        if st.sidebar.button("Đăng xuất"):
            st.session_state.is_admin = False
            st.rerun()
        return True
    st.sidebar.caption("Viewer · chỉ xem báo cáo")
    configured = bool(secrets("admin").get("password") or secrets("admin").get("password_sha256") or os.getenv("ADMIN_PASSWORD"))
    if not configured:
        st.sidebar.warning("Chưa cấu hình mật khẩu admin.")
        return False
    password = st.sidebar.text_input("Mật khẩu creator", type="password")
    if st.sidebar.button("Đăng nhập admin", width="stretch"):
        if valid_admin_password(password):
            st.session_state.is_admin = True
            st.rerun()
        else:
            st.sidebar.error("Mật khẩu không đúng.")
    return False


def apply_filters(master: pd.DataFrame, query: str, types, managers, stores, mrnd: str) -> pd.DataFrame:
    scope = master.copy()
    if query:
        needle = query.strip().lower()
        scope = scope[scope[["sku", "asin", "product_name"]].fillna("").astype(str).apply(
            lambda col: col.str.lower().str.contains(needle, regex=False)
        ).any(axis=1)]
    if types:
        scope = scope[scope["product_type"].isin(types)]
    if managers:
        scope = scope[scope["asin_manager"].isin(managers)]
    if stores:
        scope = scope[scope["store_display"].isin(stores)]
    if mrnd != "Tất cả":
        scope = scope[scope["mrnd"].eq(mrnd == "MRnD")]
    return scope


def date_pair(value):
    return value if isinstance(value, (tuple, list)) and len(value) == 2 else (value, value)


def money(value: float) -> str:
    return "USD " + f"{value:,.2f}"


def kpi_row(items: list[tuple[str, str, str]]) -> None:
    html = '<div class="kpis">' + "".join(
        f'<div class="kpi"><small>{label}</small><strong>{value}</strong><em>{note}</em></div>'
        for label, value, note in items
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@700;800&display=swap');
:root{--navy:#142b44;--orange:#f59a3d;--canvas:#f7f4ef;--muted:#718090;--line:#eadfd3}
.stApp{background:var(--canvas);color:var(--navy);font-family:'DM Sans',sans-serif}
[data-testid="stAppViewContainer"]>.main .block-container{max-width:1480px;padding:1.35rem 2.35rem 4rem}
.appbar{background:#fff;margin:-1.35rem -2.35rem 1.75rem;padding:15px 2.35rem;display:flex;justify-content:space-between;border-bottom:1px solid var(--line)}
.brand{font:800 18px Manrope,sans-serif}.sync{font-size:12px;color:var(--muted)}.sync b{color:var(--orange)}
.hero h1{color:var(--navy)!important;font:800 34px/1.15 Manrope,sans-serif;margin:18px 0 7px}.hero p,.section-sub{color:var(--muted)}
.section-title{color:var(--navy)!important;font:800 19px Manrope,sans-serif;margin:0}.section-sub{font-size:12px;margin:4px 0 14px}
div[data-testid="stVerticalBlockBorderWrapper"]{border:1px solid var(--line);border-radius:14px;background:#fff}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.kpi{padding:18px;border:1px solid var(--line);border-radius:12px;background:#fff;border-left:4px solid var(--orange)}
.kpi small{color:var(--muted);font-weight:700}.kpi strong{display:block;font:800 25px Manrope,sans-serif;margin-top:8px}.kpi em{display:block;color:#9a7b59;font-size:10px;margin-top:6px;font-style:normal}
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:10px;overflow:hidden}
.stButton button[kind="primary"]{background:var(--orange);border-color:var(--orange);font-weight:800}
@media(max-width:800px){.kpis{grid-template-columns:repeat(2,1fr)}}
</style>
""", unsafe_allow_html=True)

is_admin = admin_login()
engine, remote_storage = get_storage(db_url(), STORAGE_SCHEMA_VERSION)
# Cached resources can survive a hot reload. CREATE IF NOT EXISTS is cheap and
# guarantees that every rerun sees the current schema.
initialize_database(engine)
master = load_master(engine)
master_source = f"Product Master đã khóa · {len(master):,} ASIN" if not master.empty else "Chưa import Product Master"
orders = load_orders(engine)

st.markdown(f"""
<div class="appbar"><div class="brand">📈 Product Live Report</div><div class="sync"><b>●</b>&nbsp; {master_source}</div></div>
<div class="hero"><h1>Sales performance</h1><p>Order Report map Product Master bằng ASIN; lịch báo cáo dùng múi giờ Việt Nam.</p></div>
""", unsafe_allow_html=True)

if not remote_storage:
    st.warning("Storage hiện là local fallback. Production cần DATABASE_URL trong Streamlit Secrets để dữ liệu không mất khi restart.")

if is_admin:
    with st.expander("↑ Import & quản lý dữ liệu (Admin)", expanded=False):
        st.markdown("#### Product Master")
        master_upload = st.file_uploader(
            "Product Master · một file CSV/Excel", type=["csv", "xlsx", "xls"], key="master_upload"
        )
        st.caption("Upload mới sẽ thay thế toàn bộ Product Master hiện tại sau khi xác nhận; dữ liệu được khóa và lưu trong Supabase.")
        replace_confirmed = st.checkbox(
            "Tôi xác nhận thay thế Product Master hiện tại.",
            value=False,
            disabled=master.empty,
            key="replace_master_confirmed",
        )
        can_replace = master_upload is not None and (master.empty or replace_confirmed)
        if st.button("Kiểm tra, thay thế & khóa Product Master", type="primary", disabled=not can_replace, width="stretch"):
            try:
                cleaned_master = clean_master(read_upload(master_upload))
                result = replace_master(engine, cleaned_master, master_upload.name)
                st.success(f"Đã khóa Product Master: {result['row_count']:,} ASIN hợp lệ.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        master_history = master_import_history(engine)
        if not master_history.empty:
            st.dataframe(master_history, width="stretch", hide_index=True)

        st.divider()
        st.markdown("#### Order Report")
        order_uploads = st.file_uploader(
            "Order Report · chọn nhiều file", type=["txt", "tsv", "csv", "xlsx", "xls"],
            accept_multiple_files=True, key="order_uploads",
        )
        st.caption("Append và khóa theo batch. Timestamp: UTC → America/Los_Angeles → Asia/Ho_Chi_Minh.")
        if st.button("Kiểm tra, append & khóa Order Report", type="primary", disabled=not order_uploads, width="stretch"):
            try:
                combined = pd.concat([clean_orders(read_upload(file)) for file in order_uploads], ignore_index=True)
                combined = combined.drop_duplicates("row_hash")
                result = append_orders(engine, combined, [file.name for file in order_uploads])
                st.success(f"Đã khóa batch: thêm {result['row_count']:,} dòng; bỏ qua {result['skipped_duplicates']:,} dòng trùng.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        history = import_history(engine)
        st.markdown("#### Order import history")
        if history.empty:
            st.caption("Chưa có batch import.")
        else:
            st.dataframe(history, width="stretch", hide_index=True)
            batch = st.selectbox(
                "Batch cần xóa", history["Batch ID"],
                format_func=lambda value: f"{value[:8]} · {history.loc[history['Batch ID'].eq(value), 'Files'].iloc[0]}",
            )
            confirmed = st.checkbox("Tôi hiểu thao tác này xóa toàn bộ transaction trong batch đã khóa.")
            if st.button("Xóa batch", disabled=not confirmed):
                st.success(f"Đã xóa {delete_batch(engine, batch):,} transaction.")
                st.rerun()
else:
    st.caption("Viewer: dữ liệu đã khóa; chỉ creator/admin có quyền import, chỉnh sửa hoặc xóa.")

known_asins = set(master["asin"])
orders["mapped"] = orders["asin"].isin(known_asins) if not orders.empty else pd.Series(dtype=bool)
mapped_orders = orders[orders["mapped"]].copy() if not orders.empty else orders.copy()
today = pd.Timestamp.now(tz=VN_TZ).date()
minimum = mapped_orders["order_date"].min().date() if not mapped_orders.empty else today
maximum = mapped_orders["order_date"].max().date() if not mapped_orders.empty else today

with st.container(border=True):
    st.markdown('<p class="section-title">Bộ lọc Sale Performance</p><p class="section-sub">Date filter áp dụng trên ngày Việt Nam sau timezone conversion.</p>', unsafe_allow_html=True)
    f1, f2, f3, f4, f5, f6 = st.columns([1.35, 1.1, 1, 1, .9, .75])
    with f1:
        query = st.text_input("Tìm kiếm", placeholder="SKU, ASIN hoặc Product Name", key="sale_query")
    with f2:
        date_range = st.date_input("Khoảng thời gian", value=(minimum, maximum), key="sale_dates")
    with f3:
        selected_types = st.multiselect("Product Type", sorted(x for x in master["product_type"].unique() if x), key="sale_types")
    with f4:
        selected_managers = st.multiselect("ASIN Manager", sorted(x for x in master["asin_manager"].unique() if x), key="sale_managers")
    with f5:
        selected_stores = st.multiselect("Store", sorted(x for x in master["store_display"].unique() if x), key="sale_stores")
    with f6:
        mrnd_filter = st.selectbox("MRnD", ["Tất cả", "MRnD", "Non-MRnD"], key="sale_mrnd")

start_date, end_date = date_pair(date_range)
master_scope = apply_filters(master, query, selected_types, selected_managers, selected_stores, mrnd_filter)
period_orders = filter_dates(mapped_orders, "order_date", start_date, end_date)
period_orders = period_orders[period_orders["asin"].isin(set(master_scope["asin"]))]
summary = (
    period_orders.groupby("asin", as_index=False)
    .agg(net_revenue=("net_revenue", "sum"), orders=("order_id", "nunique"), qty=("qty", "sum"))
    .merge(master_scope, on="asin", how="inner")
) if not period_orders.empty else pd.DataFrame()

total_asin = master_scope.loc[~master_scope["status"].str.lower().eq("inactive"), "asin"].nunique()
asin_sold = summary["asin"].nunique() if not summary.empty else 0
kpi_row([
    ("REVENUE", money(summary["net_revenue"].sum() if not summary.empty else 0), "Item Price + Shipping"),
    ("ORDERS", f"{summary['orders'].sum() if not summary.empty else 0:,.0f}", "Unique Order ID"),
    ("ASIN SOLD", f"{asin_sold:,}", "Có sale trong kỳ"),
    ("TOTAL ASIN", f"{total_asin:,}", "ASIN active theo filter"),
])

st.write("")
with st.container(border=True):
    st.markdown('<p class="section-title">Sale Performance theo tuần Việt Nam</p><p class="section-sub">Revenue = cột · Orders = đường.</p>', unsafe_allow_html=True)
    sales_weekly_chart(period_orders)

st.write("")
with st.container(border=True):
    chart_col, note_col = st.columns([1.25, 1])
    with chart_col:
        st.markdown('<p class="section-title">Revenue by MRnD & Store</p><p class="section-sub">Vòng ngoài: MRnD/Non-MRnD · vòng trong: WR/PAW thuộc MRnD.</p>', unsafe_allow_html=True)
        if summary.empty:
            chart_data = pd.DataFrame(columns=["MRnD", "Store", "net_revenue"])
        else:
            chart_data = summary[["mrnd", "store_display", "net_revenue"]].copy()
            chart_data["MRnD"] = chart_data["mrnd"].map({True: "MRnD", False: "Non-MRnD"})
            chart_data["Store"] = chart_data["store_display"].replace("", "Chưa xác định")
        double_donut(chart_data, "net_revenue")
    with note_col:
        st.markdown("#### Định nghĩa")
        st.markdown("- Revenue = Item Price + Shipping Price.\n- Orders = Order ID duy nhất.\n- Wrappiness chỉ hiển thị là WR; Pawsionate chỉ hiển thị là PAW.\n- ASIN được trim + uppercase trước khi map.")

st.write("")
with st.container(border=True):
    h1, h2, h3 = st.columns([2, 1, .75])
    with h1:
        st.markdown('<p class="section-title">Product Performance</p><p class="section-sub">Hỗ trợ A→Z/Z→A và lớn→nhỏ/nhỏ→lớn.</p>', unsafe_allow_html=True)
    with h2:
        sort_column = st.selectbox("Sắp xếp", ["Revenue", "Orders", "Qty", "Product Name", "Product Type", "ASIN Manager", "Store"], label_visibility="collapsed")
    with h3:
        direction = st.selectbox("Thứ tự", ["Giảm dần / Z→A", "Tăng dần / A→Z"], label_visibility="collapsed")
    sort_map = {"Revenue": "net_revenue", "Orders": "orders", "Qty": "qty", "Product Name": "product_name", "Product Type": "product_type", "ASIN Manager": "asin_manager", "Store": "store_display"}
    if not summary.empty:
        summary = summary.sort_values(sort_map[sort_column], ascending=direction.startswith("Tăng"), na_position="last")
        display = summary[["image", "record_id", "product_name", "sku", "asin", "product_type", "store_display", "asin_manager", "mrnd", "listing_by", "custom_by", "net_revenue", "orders", "qty"]].copy()
        display["mrnd"] = display["mrnd"].map({True: "MRnD", False: "Non-MRnD"})
    else:
        display = pd.DataFrame(columns=range(14))
    display.columns = ["Image", "Record ID", "Product Name", "SKU", "ASIN", "Product Type", "Store", "ASIN Manager", "MRnD", "Listing By", "Custom By", "Revenue", "Orders", "Qty"]
    st.dataframe(display, width="stretch", hide_index=True, height=min(620, 80 + max(len(display), 5) * 35), column_config={
        "Image": st.column_config.ImageColumn("Image", width="small"),
        "Revenue": st.column_config.NumberColumn(format="USD %.2f"),
        "Orders": st.column_config.NumberColumn(format="%d"),
    })
    mapped_count = int(orders["mapped"].sum()) if not orders.empty else 0
    unmapped_count = int((~orders["mapped"]).sum()) if not orders.empty else 0
    rate = mapped_count / len(orders) if len(orders) else 0
    st.caption(f"Mapped: {mapped_count:,} · Chưa map: {unmapped_count:,} · Mapping rate: {rate:.1%}")
    st.download_button("⇩ Xuất CSV", display.to_csv(index=False).encode("utf-8-sig"), "product-live-report.csv", "text/csv")

st.write("")
with st.container(border=True):
    st.markdown('<p class="section-title">KPI theo Manage By / ASIN Manager</p><p class="section-sub">Aggregate ASIN → Record ID trước khi áp ngưỡng. New dựa trên Custom Check Done trong khoảng đang xem.</p>', unsafe_allow_html=True)
    manager_table = manager_kpis(master_scope, period_orders, start_date, end_date)
    st.dataframe(manager_table, width="stretch", hide_index=True, column_config={
        "New ASIN Revenue": st.column_config.NumberColumn(format="USD %.2f"),
        "Sold Rate": st.column_config.NumberColumn(format="%.1%%"),
        "Total Revenue": st.column_config.NumberColumn(format="USD %.2f"),
    })

st.markdown('<div class="hero"><h1>Listings Performance</h1><p>Phân tích Product Master theo Custom Check Done, độc lập với Order Date.</p></div>', unsafe_allow_html=True)
valid_custom = master.dropna(subset=["custom_check_done"]).copy()
listing_min = valid_custom["custom_check_done"].min().date() if not valid_custom.empty else today
listing_max = valid_custom["custom_check_done"].max().date() if not valid_custom.empty else today

with st.container(border=True):
    st.markdown('<p class="section-title">Bộ lọc Listings Performance</p><p class="section-sub">Mọi KPI/chart dưới đây dùng Custom Check Done làm trường thời gian chính.</p>', unsafe_allow_html=True)
    l1, l2, l3, l4, l5, l6 = st.columns([1.35, 1.1, 1, 1, .9, .75])
    with l1:
        listing_query = st.text_input("Tìm kiếm", placeholder="SKU, ASIN hoặc Product Name", key="listing_query")
    with l2:
        listing_dates = st.date_input("Custom Check Done", value=(listing_min, listing_max), key="listing_dates")
    with l3:
        listing_types = st.multiselect("Product Type", sorted(x for x in master["product_type"].unique() if x), key="listing_types")
    with l4:
        listing_managers = st.multiselect("Manage By", sorted(x for x in master["asin_manager"].unique() if x), key="listing_managers")
    with l5:
        listing_stores = st.multiselect("Store", sorted(x for x in master["store_display"].unique() if x), key="listing_stores")
    with l6:
        listing_mrnd = st.selectbox("MRnD", ["Tất cả", "MRnD", "Non-MRnD"], key="listing_mrnd")

listing_start, listing_end = date_pair(listing_dates)
listing_scope = apply_filters(valid_custom, listing_query, listing_types, listing_managers, listing_stores, listing_mrnd)
listing_scope = filter_dates(listing_scope, "custom_check_done", listing_start, listing_end).drop_duplicates("asin")
total_custom = listing_scope["asin"].nunique()
mrnd_custom = listing_scope.loc[listing_scope["mrnd"], "asin"].nunique()
non_custom = listing_scope.loc[~listing_scope["mrnd"], "asin"].nunique()
kpi_row([
    ("TOTAL CUSTOM DONE", f"{total_custom:,}", "Unique ASIN"),
    ("MRnD CUSTOM DONE", f"{mrnd_custom:,}", f"{mrnd_custom / total_custom if total_custom else 0:.1%} filtered"),
    ("NON-MRnD CUSTOM DONE", f"{non_custom:,}", f"{non_custom / total_custom if total_custom else 0:.1%} filtered"),
    ("DATE RANGE", f"{pd.Timestamp(listing_start).strftime('%d/%m')}–{pd.Timestamp(listing_end).strftime('%d/%m')}", "Theo giờ Việt Nam"),
])

st.write("")
with st.container(border=True):
    st.markdown('<p class="section-title">Custom Done mix</p><p class="section-sub">Vòng ngoài denominator = toàn bộ filtered. Vòng trong denominator riêng = MRnD thuộc WR/PAW.</p>', unsafe_allow_html=True)
    listing_chart = listing_scope[["asin", "mrnd", "store_display"]].copy()
    listing_chart["MRnD"] = listing_chart["mrnd"].map({True: "MRnD", False: "Non-MRnD"})
    listing_chart["Store"] = listing_chart["store_display"]
    listing_chart["Count"] = 1
    double_donut(listing_chart, "Count", count_mode=True)

for title, person_column in [("Manage By", "asin_manager"), ("Custom By", "custom_by")]:
    st.write("")
    with st.container(border=True):
        st.markdown(f'<p class="section-title">{title}</p><p class="section-sub">Trái: Custom Done tuần stacked MRnD/Non-MRnD. Phải: chi tiết nhân sự.</p>', unsafe_allow_html=True)
        chart_col, table_col = st.columns([1.45, 1], gap="large")
        with chart_col:
            listing_weekly_chart(listing_scope, person_column)
        with table_col:
            st.dataframe(personnel_listing_table(listing_scope, person_column), width="stretch", hide_index=True, column_config={
                "MRnD Rate": st.column_config.NumberColumn(format="%.1%%")
            })

with st.expander("Chú thích metric & cấu hình"):
    st.markdown("""
- Timezone Sale: UTC-aware → America/Los_Angeles → Asia/Ho_Chi_Minh; không localize lại timestamp đã có timezone.
- Tuần Việt Nam: Thứ Hai–Chủ Nhật; bucket hiển thị đủ range kể cả tháng không trọn vẹn.
- Record KPI: nhiều ASIN chung Record ID được cộng Revenue/Orders trước ngưỡng; các ngưỡng dùng dấu lớn hơn.
- Sold Rate: ASIN mới có sale / tổng ASIN mới; mới được xác định bằng Custom Check Done thuộc khoảng chọn.
- Persistence: production cần database.url trong Secrets; local SQLite chỉ là fallback phát triển.
""")

