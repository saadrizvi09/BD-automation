"""
insights.py — THE decision engine. Pure pandas, $0, fully explainable.

Every threshold is a named constant below and every rule is a one-sentence
heuristic you can defend in the interview. The headline output is
demand_supply_gap(): where supply is short, how many partners to recruit, and
the rupees/week leaking because of it.
"""

import math

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Named thresholds — each explainable in one sentence
# ----------------------------------------------------------------------------
RECENT_WINDOW_DAYS = 7           # "recent demand" = the last 7 days of bookings
TARGET_JOBS_PER_PARTNER_WK = 18  # a healthy active partner serves ~18 jobs/week
HIGH_CANCEL_RATE = 0.12          # >12% cancellations signals demand lost to no availability
HIGH_UTILIZATION = 16            # >16 jobs per active partner/week = stretched supply
LOW_UTILIZATION = 6              # <6 jobs per active partner/week = oversupplied
MIN_DEMAND_FOR_GAP = 15          # ignore tiny cells: need >=15 weekly bookings to flag
WOW_GROWTH_FLAG = 0.10           # demand growing >10% WoW reinforces an undersupply call

# anomaly thresholds
REV_DROP_FLAG = -0.10            # revenue down >10% WoW
CANCEL_SPIKE_FLAG = 0.50         # cancellations up >50% WoW
RATING_DROP_FLAG = -0.3          # avg rating down >0.3 WoW

# churn thresholds
CHURN_JOBS_DROP = 0.40           # jobs down >40% over 3 weeks
CHURN_MIN_RATING = 4.0           # AND rating below 4.0 ...
CHURN_IDLE_DAYS = 14             # ... OR idle more than 14 days


def _completed(bookings):
    return bookings[bookings["status"] == "completed"]


def _week_floor(s):
    """Monday-anchored week start for a datetime series."""
    return s.dt.to_period("W").apply(lambda p: p.start_time)


# ----------------------------------------------------------------------------
# KPI summary
# ----------------------------------------------------------------------------
def kpi_summary(bookings, partners=None):
    comp = _completed(bookings)
    gmv = comp["booking_value_inr"].sum()
    n_book = len(bookings)
    aov = comp["booking_value_inr"].mean() if len(comp) else 0
    completion_rate = len(comp) / n_book if n_book else 0
    active_partners = 0
    if partners is not None and len(partners):
        active_partners = int((partners["status"] == "active").sum())

    gap = demand_supply_gap(bookings, partners)
    risk = gap["est_revenue_at_risk_per_week"].sum() if len(gap) else 0.0

    return {
        "gmv": float(gmv),
        "total_bookings": int(n_book),
        "aov": float(aov),
        "active_partners": active_partners,
        "completion_rate": float(completion_rate),
        "revenue_at_risk_per_week": float(risk),
    }


# ----------------------------------------------------------------------------
# Demand-supply gap — the centerpiece
# ----------------------------------------------------------------------------
def demand_supply_gap(bookings, partners=None):
    """
    Per city x category: flag UNDERSUPPLIED cells (high demand + high utilization
    + elevated cancellations + few partners) and recommend partners to recruit,
    with rupees/week at risk. Returns a table ranked worst-gap-first.
    """
    if bookings.empty:
        return pd.DataFrame()

    max_date = bookings["date"].max()
    recent_cut = max_date - pd.Timedelta(days=RECENT_WINDOW_DAYS)
    prior_cut = recent_cut - pd.Timedelta(days=RECENT_WINDOW_DAYS)

    recent = bookings[bookings["date"] > recent_cut]
    prior = bookings[(bookings["date"] > prior_cut) & (bookings["date"] <= recent_cut)]

    grp_keys = ["city", "service_category"]

    # weekly demand (recent), prior-week demand, AOV, commission, cancel rate
    agg = recent.groupby(grp_keys).agg(
        weekly_demand=("booking_id", "count"),
        aov=("booking_value_inr", "mean"),
        commission_pct=("commission_pct", "mean"),
    ).reset_index()

    prior_demand = prior.groupby(grp_keys).size().rename("prior_demand").reset_index()
    cancels = recent.assign(_c=(recent["status"] == "cancelled").astype(int)) \
        .groupby(grp_keys)["_c"].mean().rename("cancel_rate").reset_index()

    agg = agg.merge(prior_demand, on=grp_keys, how="left") \
             .merge(cancels, on=grp_keys, how="left")
    agg["prior_demand"] = agg["prior_demand"].fillna(0)
    agg["cancel_rate"] = agg["cancel_rate"].fillna(0)
    agg["wow_growth"] = np.where(
        agg["prior_demand"] > 0,
        (agg["weekly_demand"] - agg["prior_demand"]) / agg["prior_demand"],
        0.0,
    )

    # supply: active partners per cell
    if partners is not None and len(partners):
        active = partners[partners["status"] == "active"]
        supply = active.groupby(["city", "primary_category"]).size() \
            .rename("active_partners").reset_index() \
            .rename(columns={"primary_category": "service_category"})
        agg = agg.merge(supply, on=grp_keys, how="left")
    else:
        agg["active_partners"] = np.nan
    agg["active_partners"] = agg["active_partners"].fillna(0).astype(int)

    agg["utilization"] = np.where(
        agg["active_partners"] > 0,
        agg["weekly_demand"] / agg["active_partners"],
        agg["weekly_demand"],  # no partners => everything is unmet
    )

    # ---- gap flag ----
    def classify(r):
        if r["weekly_demand"] < MIN_DEMAND_FOR_GAP:
            return "OK"
        undersupplied = (
            r["utilization"] > HIGH_UTILIZATION
            and (r["cancel_rate"] > HIGH_CANCEL_RATE or r["active_partners"] == 0)
        )
        if undersupplied:
            return "UNDERSUPPLIED"
        if r["active_partners"] > 0 and r["utilization"] < LOW_UTILIZATION:
            return "OVERSUPPLIED"
        return "OK"

    agg["gap_flag"] = agg.apply(classify, axis=1)

    # recommended partner adds = ceil(demand / target) - current_active
    agg["recommended_partner_adds"] = (
        np.ceil(agg["weekly_demand"] / TARGET_JOBS_PER_PARTNER_WK) - agg["active_partners"]
    ).clip(lower=0).astype(int)

    # rupees/week at risk = unmet+cancelled demand * AOV * commission%
    # unmet demand approximated as demand above what current partners can serve.
    served_capacity = agg["active_partners"] * TARGET_JOBS_PER_PARTNER_WK
    unmet = (agg["weekly_demand"] - served_capacity).clip(lower=0)
    cancelled_jobs = agg["weekly_demand"] * agg["cancel_rate"]
    lost_jobs = unmet + cancelled_jobs
    agg["est_revenue_at_risk_per_week"] = (
        lost_jobs * agg["aov"] * (agg["commission_pct"] / 100.0)
    )

    # only carry risk for actually-flagged cells
    agg.loc[agg["gap_flag"] != "UNDERSUPPLIED", "est_revenue_at_risk_per_week"] = 0.0
    agg.loc[agg["gap_flag"] != "UNDERSUPPLIED", "recommended_partner_adds"] = \
        agg.loc[agg["gap_flag"] != "UNDERSUPPLIED", "recommended_partner_adds"]

    ranked = agg.sort_values(
        ["est_revenue_at_risk_per_week", "weekly_demand"], ascending=False
    ).reset_index(drop=True)

    return ranked


def gap_headline(gap_table):
    """One-sentence headline string from the worst undersupplied cell.

    Prefer a high-risk cell that is ALSO growing (cleaner 'recruit, demand up'
    story); fall back to the highest-risk cell and phrase around cancellations.
    """
    under = gap_table[gap_table["gap_flag"] == "UNDERSUPPLIED"] if len(gap_table) else gap_table
    if under is None or len(under) == 0:
        return "Supply is broadly balanced — no critical undersupply this week."
    growing = under[under["wow_growth"] > 0.05]
    r = (growing if len(growing) else under).iloc[0]
    growth_clause = (f"demand {r['wow_growth']*100:+.0f}% WoW, "
                     if r["wow_growth"] > 0.05 else "")
    return (
        f"Recruit ~{int(r['recommended_partner_adds'])} partners for "
        f"{r['service_category']} in {r['city']} — {growth_clause}"
        f"{r['cancel_rate']*100:.0f}% cancellations from no availability, "
        f"{int(r['active_partners'])} active partners, "
        f"~{_inr_short(r['est_revenue_at_risk_per_week'])}/week at risk."
    )


# ----------------------------------------------------------------------------
# Anomalies
# ----------------------------------------------------------------------------
def anomalies(bookings):
    if bookings.empty:
        return []
    max_date = bookings["date"].max()
    recent_cut = max_date - pd.Timedelta(days=7)
    prior_cut = recent_cut - pd.Timedelta(days=7)
    recent = bookings[bookings["date"] > recent_cut]
    prior = bookings[(bookings["date"] > prior_cut) & (bookings["date"] <= recent_cut)]

    out = []

    def _scan(dim):
        for entity in bookings[dim].dropna().unique():
            r = recent[recent[dim] == entity]
            p = prior[prior[dim] == entity]
            if len(p) < 10:   # need a stable baseline
                continue
            rev_r = _completed(r)["booking_value_inr"].sum()
            rev_p = _completed(p)["booking_value_inr"].sum()
            if rev_p > 0:
                chg = (rev_r - rev_p) / rev_p
                if chg < REV_DROP_FLAG:
                    out.append({
                        "entity": f"{entity}", "metric": "revenue",
                        "change": chg,
                        "severity": "high" if chg < -0.20 else "medium",
                        "text": f"{entity} revenue down {abs(chg)*100:.0f}% WoW",
                    })
            # cancellations
            cr_r = (r["status"] == "cancelled").mean() if len(r) else 0
            cr_p = (p["status"] == "cancelled").mean() if len(p) else 0
            if cr_p > 0 and (cr_r - cr_p) / cr_p > CANCEL_SPIKE_FLAG and cr_r > 0.08:
                out.append({
                    "entity": f"{entity}", "metric": "cancellations",
                    "change": (cr_r - cr_p) / cr_p,
                    "severity": "high" if cr_r > 0.18 else "medium",
                    "text": f"{entity} cancellations up {((cr_r-cr_p)/cr_p)*100:.0f}% WoW ({cr_r*100:.0f}% now)",
                })
            # rating
            rt_r = r["rating"].mean()
            rt_p = p["rating"].mean()
            if pd.notna(rt_r) and pd.notna(rt_p) and (rt_r - rt_p) < RATING_DROP_FLAG:
                out.append({
                    "entity": f"{entity}", "metric": "rating",
                    "change": rt_r - rt_p,
                    "severity": "medium",
                    "text": f"{entity} avg rating down {abs(rt_r-rt_p):.1f} WoW (now {rt_r:.1f})",
                })

    _scan("city")
    _scan("service_category")

    sev_order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda a: (sev_order.get(a["severity"], 3), -abs(a["change"])))
    return out


# ----------------------------------------------------------------------------
# Churn risk
# ----------------------------------------------------------------------------
def churn_risk(partners, bookings):
    if partners is None or partners.empty or bookings.empty:
        return {"count": 0, "by_city": {}, "partners": []}

    active = partners[partners["status"] == "active"].copy()
    if active.empty:
        return {"count": 0, "by_city": {}, "partners": []}

    max_date = bookings["date"].max()
    w1 = bookings[bookings["date"] > max_date - pd.Timedelta(days=7)]
    w3_start = max_date - pd.Timedelta(days=21)
    last3 = bookings[bookings["date"] > w3_start]

    jobs_recent = w1.groupby("partner_id").size().rename("jobs_last_wk")
    jobs_3wk_avg = (last3.groupby("partner_id").size() / 3.0).rename("jobs_3wk_avg")
    last_seen = bookings.groupby("partner_id")["date"].max().rename("last_seen")

    a = active.merge(jobs_recent, on="partner_id", how="left") \
              .merge(jobs_3wk_avg, on="partner_id", how="left") \
              .merge(last_seen, on="partner_id", how="left")
    a["jobs_last_wk"] = a["jobs_last_wk"].fillna(0)
    a["jobs_3wk_avg"] = a["jobs_3wk_avg"].fillna(0)
    a["idle_days"] = (max_date - a["last_seen"]).dt.days
    a["idle_days"] = a["idle_days"].fillna(999)

    a["jobs_drop"] = np.where(
        a["jobs_3wk_avg"] > 0,
        (a["jobs_3wk_avg"] - a["jobs_last_wk"]) / a["jobs_3wk_avg"],
        0,
    )

    at_risk = a[
        (a["jobs_drop"] > CHURN_JOBS_DROP)
        & ((a["avg_rating"].fillna(5) < CHURN_MIN_RATING) | (a["idle_days"] > CHURN_IDLE_DAYS))
    ]

    by_city = at_risk.groupby("city").size().sort_values(ascending=False).to_dict()
    plist = at_risk[["partner_id", "name", "city", "primary_category",
                     "avg_rating", "idle_days", "jobs_drop"]].to_dict("records")
    return {"count": int(len(at_risk)), "by_city": by_city, "partners": plist}


# ----------------------------------------------------------------------------
# Forecast + suggested targets
# ----------------------------------------------------------------------------
def forecast(bookings):
    """Next-week projection via trailing 4-week moving average + linear trend."""
    if bookings.empty:
        return {"overall": {}, "by_city": {}}
    comp = _completed(bookings).copy()
    comp["week"] = _week_floor(comp["date"])

    weekly = comp.groupby("week").agg(
        bookings=("booking_id", "count"),
        revenue=("booking_value_inr", "sum"),
    ).reset_index().sort_values("week")

    # drop the partial current week from the fit if present
    full = weekly.iloc[:-1] if len(weekly) > 4 else weekly

    def _project(series):
        tail = series.tail(4).values.astype(float)
        if len(tail) < 2:
            return float(tail[-1]) if len(tail) else 0.0
        ma = tail.mean()
        x = np.arange(len(tail))
        slope = np.polyfit(x, tail, 1)[0]
        return float(max(0.0, ma + slope))  # MA nudged by recent trend

    overall = {
        "next_week_bookings": round(_project(full["bookings"])),
        "next_week_revenue": _project(full["revenue"]),
        "method": "trailing 4-week moving average nudged by linear trend",
    }

    by_city = {}
    for city in comp["city"].unique():
        cw = comp[comp["city"] == city].groupby(_week_floor(comp[comp["city"] == city]["date"]))
        cs = comp[comp["city"] == city].copy()
        cs["week"] = _week_floor(cs["date"])
        wk = cs.groupby("week")["booking_value_inr"].sum()
        wkf = wk.iloc[:-1] if len(wk) > 4 else wk
        by_city[city] = _project(wkf)

    return {"overall": overall, "by_city": by_city}


def suggested_targets(bookings, growth=0.05):
    """Forecast x (1+growth); flag cities tracking below trend."""
    fc = forecast(bookings)
    overall = fc["overall"]
    targets = {
        "target_bookings": round(overall.get("next_week_bookings", 0) * (1 + growth)),
        "target_revenue": overall.get("next_week_revenue", 0) * (1 + growth),
        "growth_factor": growth,
    }
    # cities below their own forecast in the latest full week
    comp = _completed(bookings).copy()
    below = []
    if not comp.empty:
        comp["week"] = _week_floor(comp["date"])
        weeks = sorted(comp["week"].unique())
        if len(weeks) >= 2:
            last_full = weeks[-2]
            actual = comp[comp["week"] == last_full].groupby("city")["booking_value_inr"].sum()
            for city, proj in fc["by_city"].items():
                act = actual.get(city, 0)
                if proj > 0 and act < proj * 0.9:
                    below.append(city)
    targets["cities_below_trend"] = below
    return targets


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _inr_short(v):
    v = float(v)
    if v >= 1e7:
        return f"₹{v/1e7:.1f}Cr"
    if v >= 1e5:
        return f"₹{v/1e5:.1f}L"
    if v >= 1e3:
        return f"₹{v/1e3:.0f}K"
    return f"₹{v:.0f}"


def inr(v):
    """Full Indian-format rupee string with commas."""
    v = float(v)
    s = f"{abs(v):,.0f}"
    return ("-" if v < 0 else "") + "₹" + s
