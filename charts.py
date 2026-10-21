from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from report_logic import VN_TZ, add_week_bucket


ORANGE = "#f59a3d"
NAVY = "#27445f"


def period_display(mode: str) -> str:
    return {"Năm": "Quý + Năm", "Quý": "Tháng + Năm", "Tháng": "Tuần + Tháng"}.get(
        mode, "Tuần + Tháng"
    )


def add_period_bucket(df: pd.DataFrame, date_column: str, mode: str) -> pd.DataFrame:
    """Bucket VN timestamps based on the quick range selected by the viewer."""
    if mode == "Tháng":
        result = add_week_bucket(df, date_column)
        return result.rename(columns={"week_start": "period_start", "week_label": "period_label"})

    result = df.copy()
    local_naive = result[date_column].dt.tz_convert(VN_TZ).dt.tz_localize(None)
    if mode == "Năm":
        result["period_start"] = local_naive.dt.to_period("Q").dt.start_time
        result["period_label"] = "Q" + local_naive.dt.quarter.astype(str) + "/" + local_naive.dt.year.astype(str)
    else:
        result["period_start"] = local_naive.dt.to_period("M").dt.start_time
        result["period_label"] = "Tháng " + local_naive.dt.strftime("%m/%Y")
    return result


def sales_weekly_chart(orders: pd.DataFrame, mode: str = "Tháng") -> None:
    if orders.empty:
        st.info("Không có sale trong khoảng thời gian đã chọn.")
        return
    work = add_period_bucket(orders, "order_date", mode)
    weekly = work.groupby(["period_start", "period_label"], as_index=False).agg(
        Revenue=("net_revenue", "sum"), Orders=("order_id", "nunique")
    ).sort_values("period_start")
    order = weekly["period_label"].tolist()
    base = alt.Chart(weekly).encode(
        x=alt.X("period_label:N", sort=order, title=period_display(mode))
    )
    bars = base.mark_bar(color=ORANGE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        y=alt.Y("Revenue:Q", title="Revenue (USD)", axis=alt.Axis(format=",.0f")),
        tooltip=["period_label:N", alt.Tooltip("Revenue:Q", format=",.2f"), "Orders:Q"],
    )
    line = base.mark_line(color=NAVY, point=True, strokeWidth=3).encode(
        y=alt.Y("Orders:Q", title="Orders", axis=alt.Axis(orient="right")),
        tooltip=["period_label:N", "Orders:Q"],
    )
    st.altair_chart(
        (bars + line).resolve_scale(y="independent").properties(height=340),
        use_container_width=True,
    )
    if mode == "Tháng":
        st.caption("Tuần Thứ Hai-Chủ Nhật theo múi giờ Việt Nam; nhãn là ngày bắt đầu-kết thúc.")
    else:
        st.caption(f"Dữ liệu theo {period_display(mode).lower()}, dùng ngày Việt Nam sau timezone conversion.")


def manager_sales_chart(orders: pd.DataFrame, master_scope: pd.DataFrame, mode: str = "Tháng") -> None:
    if orders.empty or master_scope.empty:
        st.info("Không có sale theo ASIN Manager trong khoảng thời gian đã chọn.")
        return
    manager_map = master_scope[["asin", "asin_manager"]].drop_duplicates("asin")
    work = orders.merge(manager_map, on="asin", how="inner")
    if work.empty:
        st.info("Không có sale theo ASIN Manager trong khoảng thời gian đã chọn.")
        return
    work["ASIN Manager"] = work["asin_manager"].fillna("").astype(str).str.strip().replace("", "Chưa xác định")
    work = add_period_bucket(work, "order_date", mode)
    grouped = work.groupby(
        ["period_start", "period_label", "ASIN Manager"], as_index=False
    ).agg(Revenue=("net_revenue", "sum"), Orders=("order_id", "nunique"))
    grouped = grouped.sort_values(["period_start", "ASIN Manager"])
    order = grouped["period_label"].drop_duplicates().tolist()
    color = alt.Color("ASIN Manager:N", title="ASIN Manager")
    bars = alt.Chart(grouped).mark_bar(opacity=.82).encode(
        x=alt.X("period_label:N", sort=order, title=period_display(mode)),
        y=alt.Y("Revenue:Q", title="Revenue (USD)", stack="zero", axis=alt.Axis(format=",.0f")),
        color=color,
        tooltip=["period_label:N", "ASIN Manager:N", alt.Tooltip("Revenue:Q", format=",.2f"), "Orders:Q"],
    )
    lines = alt.Chart(grouped).mark_line(point=True, strokeWidth=2.5).encode(
        x=alt.X("period_label:N", sort=order),
        y=alt.Y("Orders:Q", title="Orders", axis=alt.Axis(orient="right")),
        color=color,
        detail="ASIN Manager:N",
        tooltip=["period_label:N", "ASIN Manager:N", "Orders:Q"],
    )
    st.altair_chart(
        (bars + lines).resolve_scale(y="independent").properties(height=360),
        use_container_width=True,
    )
    st.caption("Revenue = cột stacked theo ASIN Manager · Orders = đường theo ASIN Manager.")


def double_donut(
    data: pd.DataFrame,
    value_column: str,
    count_mode: bool = False,
    inner_status: str | None = "MRnD",
) -> None:
    if data.empty or data[value_column].sum() <= 0:
        st.info("Không có dữ liệu trong bộ lọc hiện tại.")
        return
    value_format = ",.0f" if count_mode else ",.2f"
    outer = data.groupby("MRnD", as_index=False)[value_column].sum()
    outer["percent"] = outer[value_column] / outer[value_column].sum()
    outer["outer_label"] = outer.apply(
        lambda row: (
            f"{row['MRnD']} · {row[value_column]:,.0f} · {row['percent']:.1%}"
            if count_mode else f"{row['MRnD']} · {row['percent']:.1%}"
        ),
        axis=1,
    )
    outer_arc = alt.Chart(outer).mark_arc(innerRadius=105, outerRadius=145, stroke="white", strokeWidth=2).encode(
        theta=alt.Theta(f"{value_column}:Q"),
        color=alt.Color("outer_label:N", scale=alt.Scale(range=[ORANGE, NAVY]), title="Tổng theo MRnD"),
        tooltip=["MRnD:N", alt.Tooltip(f"{value_column}:Q", format=value_format), alt.Tooltip("percent:Q", format=".1%")],
    )
    outer_text = alt.Chart(outer).mark_text(
        radius=125, fontSize=12, fontWeight="bold", color="white"
    ).encode(
        theta=alt.Theta(f"{value_column}:Q"),
        text=alt.Text("percent:Q", format=".1%"),
    )
    inner_source = data[data["Store"].isin(["WR", "PAW"])]
    if inner_status is not None:
        inner_source = inner_source[inner_source["MRnD"] == inner_status]
    inner = inner_source.groupby("Store", as_index=False)[value_column].sum()
    if inner.empty or inner[value_column].sum() <= 0:
        st.altair_chart((outer_arc + outer_text).properties(height=360), use_container_width=True)
        return
    inner["percent"] = inner[value_column] / inner[value_column].sum()
    inner["inner_label"] = inner.apply(
        lambda row: (
            f"{row['Store']} · {row[value_column]:,.0f} · {row['percent']:.1%}"
            if count_mode else f"{row['Store']} · {row['percent']:.1%}"
        ),
        axis=1,
    )
    inner_arc = alt.Chart(inner).mark_arc(innerRadius=38, outerRadius=96, stroke="white", strokeWidth=2).encode(
        theta=alt.Theta(f"{value_column}:Q"),
        color=alt.Color(
            "inner_label:N",
            scale=alt.Scale(range=["#e78024", "#5d82a3"]),
            title=f"{inner_status}: WR / PAW" if inner_status else "Store: WR / PAW",
        ),
        tooltip=["Store:N", alt.Tooltip(f"{value_column}:Q", format=value_format), alt.Tooltip("percent:Q", format=".1%")],
    )
    inner_text = alt.Chart(inner).mark_text(
        radius=67, fontSize=11, fontWeight="bold", color="white"
    ).encode(
        theta=alt.Theta(f"{value_column}:Q"),
        text=alt.Text("percent:Q", format=".1%"),
    )
    st.altair_chart(
        alt.layer(outer_arc, outer_text, inner_arc, inner_text)
        .resolve_scale(color="independent")
        .properties(height=380),
        use_container_width=True,
    )


def listing_weekly_chart(scope: pd.DataFrame, person_column: str, mode: str = "Tháng") -> None:
    work = scope[scope[person_column].fillna("").astype(str).str.strip().ne("")].copy()
    if work.empty:
        st.info("Không có dữ liệu nhân sự trong bộ lọc hiện tại.")
        return
    work = add_period_bucket(work, "custom_check_done", mode)
    work["MRnD Status"] = work["mrnd"].map({True: "MRnD", False: "Non-MRnD"})
    weekly = work.groupby(["period_start", "period_label", "MRnD Status"], as_index=False)["asin"].nunique().rename(columns={"asin": "Custom Done"}).sort_values("period_start")
    weekly["Status Order"] = weekly["MRnD Status"].map({"Non-MRnD": 0, "MRnD": 1})
    weekly = weekly.sort_values(["period_start", "Status Order"])
    weekly["Stack Start"] = weekly.groupby("period_label")["Custom Done"].cumsum() - weekly["Custom Done"]
    weekly["Label Position"] = weekly["Stack Start"] + weekly["Custom Done"] / 2
    order = weekly["period_label"].drop_duplicates().tolist()
    chart = alt.Chart(weekly).mark_bar().encode(
        x=alt.X("period_label:N", sort=order, title=period_display(mode)),
        y=alt.Y("Custom Done:Q", title="Count Custom Done", stack="zero"),
        color=alt.Color("MRnD Status:N", scale=alt.Scale(domain=["MRnD", "Non-MRnD"], range=[ORANGE, NAVY])),
        order=alt.Order("Status Order:Q", sort="ascending"),
        tooltip=["period_label:N", "MRnD Status:N", "Custom Done:Q"],
    )
    labels = alt.Chart(weekly).mark_text(
        color="white", fontWeight="bold", fontSize=12, baseline="middle"
    ).encode(
        x=alt.X("period_label:N", sort=order),
        y=alt.Y("Label Position:Q"),
        text=alt.Text("Custom Done:Q", format=".0f"),
        tooltip=["period_label:N", "MRnD Status:N", "Custom Done:Q"],
    )
    st.altair_chart((chart + labels).properties(height=330), use_container_width=True)
    if mode == "Tháng":
        st.caption("Đếm unique ASIN có Custom Check Done; tuần Thứ Hai-Chủ Nhật theo giờ Việt Nam.")
    else:
        st.caption(f"Đếm unique ASIN có Custom Check Done theo {period_display(mode).lower()}.")

