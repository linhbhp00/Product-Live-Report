from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from report_logic import add_week_bucket


ORANGE = "#f59a3d"
NAVY = "#27445f"


def sales_weekly_chart(orders: pd.DataFrame) -> None:
    if orders.empty:
        st.info("Không có sale trong khoảng thời gian đã chọn.")
        return
    work = add_week_bucket(orders, "order_date")
    weekly = work.groupby(["week_start", "week_label"], as_index=False).agg(
        Revenue=("net_revenue", "sum"), Orders=("order_id", "nunique")
    ).sort_values("week_start")
    order = weekly["week_label"].tolist()
    base = alt.Chart(weekly).encode(x=alt.X("week_label:N", sort=order, title="Tuần Việt Nam"))
    bars = base.mark_bar(color=ORANGE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        y=alt.Y("Revenue:Q", title="Revenue (USD)", axis=alt.Axis(format=",.0f")),
        tooltip=["week_label:N", alt.Tooltip("Revenue:Q", format=",.2f"), "Orders:Q"],
    )
    line = base.mark_line(color=NAVY, point=True, strokeWidth=3).encode(
        y=alt.Y("Orders:Q", title="Orders", axis=alt.Axis(orient="right")), tooltip=["week_label:N", "Orders:Q"]
    )
    st.altair_chart(
        (bars + line).resolve_scale(y="independent").properties(height=340),
        use_container_width=True,
    )
    st.caption("Tuần Thứ Hai-Chủ Nhật theo múi giờ Việt Nam; nhãn là ngày bắt đầu-kết thúc.")


def double_donut(
    data: pd.DataFrame,
    value_column: str,
    count_mode: bool = False,
    inner_mrnd_only: bool = True,
) -> None:
    if data.empty or data[value_column].sum() <= 0:
        st.info("Không có dữ liệu trong bộ lọc hiện tại.")
        return
    value_format = ",.0f" if count_mode else ",.2f"
    outer = data.groupby("MRnD", as_index=False)[value_column].sum()
    outer["percent"] = outer[value_column] / outer[value_column].sum()
    outer["label"] = outer.apply(lambda row: f"{row['MRnD']} · {row['percent']:.1%}", axis=1)
    outer_arc = alt.Chart(outer).mark_arc(innerRadius=105, outerRadius=145, stroke="white", strokeWidth=2).encode(
        theta=alt.Theta(f"{value_column}:Q"),
        color=alt.Color("label:N", scale=alt.Scale(range=[ORANGE, NAVY]), title="Tổng theo MRnD"),
        tooltip=["MRnD:N", alt.Tooltip(f"{value_column}:Q", format=value_format), alt.Tooltip("percent:Q", format=".1%")],
    )
    outer_text = alt.Chart(outer).mark_text(
        radius=125, fontSize=12, fontWeight="bold", color="white"
    ).encode(
        theta=alt.Theta(f"{value_column}:Q"),
        text=alt.Text("percent:Q", format=".1%"),
    )
    inner_source = data[data["Store"].isin(["WR", "PAW"])]
    if inner_mrnd_only:
        inner_source = inner_source[inner_source["MRnD"] == "MRnD"]
    inner = inner_source.groupby("Store", as_index=False)[value_column].sum()
    if inner.empty or inner[value_column].sum() <= 0:
        st.altair_chart((outer_arc + outer_text).properties(height=360), use_container_width=True)
        return
    inner["percent"] = inner[value_column] / inner[value_column].sum()
    inner["label"] = inner.apply(lambda row: f"{row['Store']} · {row['percent']:.1%}", axis=1)
    inner_arc = alt.Chart(inner).mark_arc(innerRadius=38, outerRadius=96, stroke="white", strokeWidth=2).encode(
        theta=alt.Theta(f"{value_column}:Q"),
        color=alt.Color(
            "label:N",
            scale=alt.Scale(range=["#e78024", "#5d82a3"]),
            title="MRnD: WR / PAW" if inner_mrnd_only else "Store: WR / PAW",
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
        (inner_arc + inner_text + outer_arc + outer_text).resolve_scale(color="independent").properties(height=380),
        use_container_width=True,
    )


def listing_weekly_chart(scope: pd.DataFrame, person_column: str) -> None:
    work = scope[scope[person_column].fillna("").astype(str).str.strip().ne("")].copy()
    if work.empty:
        st.info("Không có dữ liệu nhân sự trong bộ lọc hiện tại.")
        return
    work = add_week_bucket(work, "custom_check_done")
    work["MRnD Status"] = work["mrnd"].map({True: "MRnD", False: "Non-MRnD"})
    weekly = work.groupby(["week_start", "week_label", "MRnD Status"], as_index=False)["asin"].nunique().rename(columns={"asin": "Custom Done"}).sort_values("week_start")
    order = weekly["week_label"].drop_duplicates().tolist()
    chart = alt.Chart(weekly).mark_bar().encode(
        x=alt.X("week_label:N", sort=order, title="Tuần Việt Nam"),
        y=alt.Y("Custom Done:Q", title="Count Custom Done", stack="zero"),
        color=alt.Color("MRnD Status:N", scale=alt.Scale(domain=["MRnD", "Non-MRnD"], range=[ORANGE, NAVY])),
        tooltip=["week_label:N", "MRnD Status:N", "Custom Done:Q"],
    ).properties(height=330)
    st.altair_chart(chart, use_container_width=True)
    st.caption("Đếm unique ASIN có Custom Check Done; tuần Thứ Hai-Chủ Nhật theo giờ Việt Nam.")

