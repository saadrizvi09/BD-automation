"""
charts.py — 8 polished plotly figures, each tied to a BD question.

The LLM never draws a chart. These are pure pandas + plotly. Styling aims for
"a real analyst's polished deck": ₹ formatting, % labels, sorted bars, titles.
build_all(bookings, partners) returns a dict of {key: figure}.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from insights import _completed, _week_floor, forecast

# clean, professional palette
PALETTE = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2",
           "#db2777", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#b91c1c"]

LAYOUT = dict(
    template="plotly_white",
    title_font=dict(size=18, color="#0f172a"),
    font=dict(family="Segoe UI, Arial", size=13, color="#334155"),
    margin=dict(l=50, r=30, t=60, b=50),
    legend=dict(orientation="h", yanchor="bottom", y=-0.25),
)


def _inr_axis(fig, axis="y"):
    fig.update_layout(**{f"{axis}axis": dict(tickprefix="₹", separatethousands=True)})


def revenue_by_category(bookings):
    comp = _completed(bookings)
    d = comp.groupby("service_category")["booking_value_inr"].sum().sort_values(ascending=False)
    fig = px.pie(
        names=d.index, values=d.values, hole=0.0,
        title="Revenue share by service category",
        color_discrete_sequence=PALETTE,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(**LAYOUT)
    return fig


def bookings_by_city(bookings):
    d = bookings.groupby("city").size().sort_values(ascending=False)
    fig = px.pie(
        names=d.index, values=d.values, hole=0.55,
        title="Booking share by city",
        color_discrete_sequence=PALETTE,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(**LAYOUT)
    return fig


def revenue_by_city(bookings):
    comp = _completed(bookings)
    d = comp.groupby("city")["booking_value_inr"].sum().sort_values(ascending=False)
    fig = px.bar(
        x=d.values, y=d.index, orientation="h",
        title="Revenue by city",
        color_discrete_sequence=["#2563eb"],
        text=[f"₹{v/1e5:.1f}L" for v in d.values],
    )
    fig.update_layout(**LAYOUT)
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(title="Revenue", tickprefix="₹", separatethousands=True)
    fig.update_traces(textposition="outside")
    return fig


def wow_trend(bookings):
    comp = _completed(bookings).copy()
    comp["week"] = _week_floor(comp["date"])
    w = comp.groupby("week").agg(
        bookings=("booking_id", "count"),
        revenue=("booking_value_inr", "sum"),
    ).reset_index().sort_values("week")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=w["week"], y=w["bookings"], name="Bookings", mode="lines+markers",
        line=dict(color="#2563eb", width=3), yaxis="y1",
    ))
    fig.add_trace(go.Scatter(
        x=w["week"], y=w["revenue"], name="Revenue", mode="lines+markers",
        line=dict(color="#16a34a", width=3), yaxis="y2",
    ))

    # dashed forecast segment for revenue
    fc = forecast(bookings)
    if len(w) >= 2:
        last_week = w["week"].iloc[-1]
        next_week = last_week + pd.Timedelta(days=7)
        fig.add_trace(go.Scatter(
            x=[w["week"].iloc[-1], next_week],
            y=[w["revenue"].iloc[-1], fc["overall"]["next_week_revenue"]],
            name="Revenue forecast", mode="lines+markers",
            line=dict(color="#16a34a", width=2, dash="dash"),
            yaxis="y2",
        ))

    fig.update_layout(
        title="Week-over-week bookings & revenue (dashed = next-week forecast)",
        yaxis=dict(title="Bookings", side="left"),
        yaxis2=dict(title="Revenue (₹)", overlaying="y", side="right",
                    tickprefix="₹", separatethousands=True),
        **{k: v for k, v in LAYOUT.items() if k not in ("title",)},
    )
    return fig


def onboarding_funnel(partners):
    if partners is None or partners.empty:
        return _empty("Partner onboarding funnel (no partner data)")
    order = ["applied", "onboarded", "active", "churned"]
    counts = partners["status"].value_counts()
    # cumulative funnel: applied includes all who ever applied
    vals = []
    running = partners.shape[0]
    stage_counts = {s: int(counts.get(s, 0)) for s in order}
    # show funnel as applied -> onboarded -> active (drop-off)
    applied = sum(stage_counts.values())
    onboarded = stage_counts["onboarded"] + stage_counts["active"] + stage_counts["churned"]
    active = stage_counts["active"]
    fig = go.Figure(go.Funnel(
        y=["Applied", "Onboarded", "Active"],
        x=[applied, onboarded, active],
        textinfo="value+percent initial",
        marker=dict(color=["#93c5fd", "#3b82f6", "#1d4ed8"]),
    ))
    fig.update_layout(title="Partner onboarding funnel", **{k: v for k, v in LAYOUT.items() if k != "title"})
    return fig


def demand_supply_chart(bookings, partners):
    comp = _completed(bookings)
    demand = bookings.groupby("city").size().rename("bookings")
    if partners is not None and len(partners):
        active = partners[partners["status"] == "active"].groupby("city").size().rename("active_partners")
    else:
        active = pd.Series(dtype=int, name="active_partners")
    d = pd.concat([demand, active], axis=1).fillna(0).sort_values("bookings", ascending=False)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=d.index, y=d["bookings"], name="Bookings (demand)",
                         marker_color="#2563eb", yaxis="y1"))
    fig.add_trace(go.Bar(x=d.index, y=d["active_partners"], name="Active partners (supply)",
                         marker_color="#f59e0b", yaxis="y2"))
    fig.update_layout(
        title="Demand vs supply by city — short bars on supply = recruit here",
        barmode="group",
        yaxis=dict(title="Bookings"),
        yaxis2=dict(title="Active partners", overlaying="y", side="right"),
        **{k: v for k, v in LAYOUT.items() if k != "title"},
    )
    return fig


def status_by_category(bookings):
    d = bookings.groupby(["service_category", "status"]).size().unstack(fill_value=0)
    for s in ["completed", "cancelled", "rescheduled"]:
        if s not in d.columns:
            d[s] = 0
    d = d.loc[d.sum(axis=1).sort_values(ascending=False).index]
    fig = go.Figure()
    colors = {"completed": "#16a34a", "cancelled": "#dc2626", "rescheduled": "#f59e0b"}
    for s in ["completed", "cancelled", "rescheduled"]:
        fig.add_trace(go.Bar(x=d.index, y=d[s], name=s.capitalize(), marker_color=colors[s]))
    fig.update_layout(title="Booking outcomes by category", barmode="stack",
                      **{k: v for k, v in LAYOUT.items() if k != "title"})
    fig.update_xaxes(tickangle=-30)
    return fig


def top_aov(bookings):
    comp = _completed(bookings)
    d = comp.groupby("service_category")["booking_value_inr"].mean().sort_values(ascending=False).head(10)
    fig = px.bar(
        x=d.values, y=d.index, orientation="h",
        title="Top services by average order value (AOV)",
        color_discrete_sequence=["#7c3aed"],
        text=[f"₹{v:,.0f}" for v in d.values],
    )
    fig.update_layout(**LAYOUT)
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(title="AOV", tickprefix="₹", separatethousands=True)
    fig.update_traces(textposition="outside")
    return fig


def _empty(title):
    fig = go.Figure()
    fig.update_layout(title=title, **{k: v for k, v in LAYOUT.items() if k != "title"})
    return fig


# ----------------------------------------------------------------------------
# Dynamic chart for the chat box — built from a query result + the parsed intent
# ----------------------------------------------------------------------------
_METRIC_LABEL = {"revenue": "Revenue", "gmv": "Revenue", "bookings": "Bookings",
                 "aov": "AOV", "rating": "Avg rating", "cancellations": "Cancellation %"}


def dynamic_chart(result_df, intent):
    """Turn a chat query result (a 1-column DataFrame indexed by the group) into
    a pie / bar / line figure, per the intent's chart_type. Returns None when a
    chart doesn't make sense (no grouping, empty data, or chart_type 'none')."""
    if result_df is None or len(result_df) == 0:
        return None
    intent = intent or {}
    group_by = intent.get("group_by")
    ctype = intent.get("chart_type", "bar")
    if not group_by or ctype in (None, "none"):
        return None

    s = result_df.iloc[:, 0].dropna()
    if len(s) == 0:
        return None

    metric = intent.get("metric", "value")
    label = _METRIC_LABEL.get(metric, str(metric).replace("_", " ").title())
    ml = str(metric).lower()
    is_money = metric in ("revenue", "gmv", "aov") or any(
        k in ml for k in ("inr", "revenue", "gmv", "aov", "amount", "value",
                          "sales", "price", "cost", "spend", "₹"))
    agg = intent.get("agg")
    prefix = {"mean": "Avg ", "min": "Min ", "max": "Max ",
              "median": "Median "}.get(agg, "")
    labels = [str(i) for i in s.index]
    values = [float(v) for v in s.values]
    title = f"{prefix}{label} by {str(group_by).replace('_', ' ')}"

    if ctype == "pie":
        fig = px.pie(names=labels, values=values, title=title,
                     color_discrete_sequence=PALETTE)
        fig.update_traces(textposition="inside", textinfo="percent+label")
    elif ctype == "line":
        fig = px.line(x=labels, y=values, markers=True, title=title,
                      color_discrete_sequence=["#2563eb"])
        if is_money:
            fig.update_yaxes(tickprefix="₹", separatethousands=True)
    else:  # bar (default) — horizontal, ranked
        txt = [f"₹{v:,.0f}" if is_money else f"{v:,.0f}" for v in values]
        fig = px.bar(x=values, y=labels, orientation="h", title=title,
                     color_discrete_sequence=["#2563eb"], text=txt)
        fig.update_yaxes(autorange="reversed", title="")
        if is_money:
            fig.update_xaxes(tickprefix="₹", separatethousands=True)
        fig.update_traces(textposition="outside")

    fig.update_layout(**LAYOUT)
    return fig


def build_all(bookings, partners=None):
    return {
        "revenue_by_category": revenue_by_category(bookings),
        "bookings_by_city": bookings_by_city(bookings),
        "revenue_by_city": revenue_by_city(bookings),
        "wow_trend": wow_trend(bookings),
        "onboarding_funnel": onboarding_funnel(partners),
        "demand_supply": demand_supply_chart(bookings, partners),
        "status_by_category": status_by_category(bookings),
        "top_aov": top_aov(bookings),
    }
