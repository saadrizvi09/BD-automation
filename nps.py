"""
nps.py — automates the company "NPS & Ratings" tracker: the weekly WTD / MoM
SUMIFS grid that an analyst rebuilds off a raw ratings [DUMP] tab.

What the source spreadsheet does (so you can explain it in the interview):
an analyst dumps raw job ratings into a [DUMP] tab, then SUMIFS/LET formulas
compute — per week and per month — the NPS (promoters − detractors), the average
rating, the ratings conversion (ratings ÷ bids), and the share of good vs poor
ratings, plus the same split by job type, with week-over-week and month-over-month
deltas. We reproduce all of that in pure pandas from the cleaned bookings (which
carry date, rating and service_category = "job type"). $0, transparent, instant.

NPS on a 5-star scale (standard — and adjustable via the named constants below):
  Promoter = 5★ · Passive = 4★ · Detractor = 1–3★
  NPS% = (promoters − detractors) / rated × 100
"""

import numpy as np
import pandas as pd

# --- named, explainable thresholds (one place to change if your firm differs) ---
PROMOTER_MIN = 5       # ratings >= 5  → promoter
DETRACTOR_MAX = 3      # ratings <= 3  → detractor   (4★ = passive, in between)
GOOD_MIN = 5           # "good" rating = 5★
POOR_MAX = 3           # "poor" rating = ≤3★
JOB_COL = "service_category"   # the "job type" dimension in the company sheet
RATING_COL = "rating"
DATE_COL = "date"


def has_ratings(df):
    """True if this table can drive an NPS tracker (needs a rating + date column)."""
    return (df is not None and len(df)
            and RATING_COL in df.columns and DATE_COL in df.columns
            and pd.to_numeric(df[RATING_COL], errors="coerce").notna().any())


def _counts(ratings):
    """Bucket a rating series into promoters / passives / detractors + NPS%."""
    n = int(len(ratings))
    prom = int((ratings >= PROMOTER_MIN).sum())
    det = int((ratings <= DETRACTOR_MAX).sum())
    pas = n - prom - det
    nps = round((prom - det) / n * 100, 1) if n else 0.0
    return prom, pas, det, n, nps


def tracker(df, freq="W"):
    """The core grid: one row per period (week or month) with every metric the
    company sheet tracks, plus the WoW/MoM delta on NPS and average rating.
    freq='W' → weekly (WTD), freq='M' → monthly (MoM)."""
    d = df.copy()
    d[DATE_COL] = pd.to_datetime(d[DATE_COL], errors="coerce")
    d = d.dropna(subset=[DATE_COL])
    if d.empty:
        return pd.DataFrame()
    d["period"] = d[DATE_COL].dt.to_period(freq)

    rows = []
    for per, g in d.groupby("period"):
        ratings = pd.to_numeric(g[RATING_COL], errors="coerce").dropna()
        prom, pas, det, n, nps = _counts(ratings)
        bids = len(g)                                      # all bookings = "bids"
        avg = round(float(ratings.mean()), 2) if n else np.nan
        conv = round(n / bids * 100, 1) if bids else 0.0   # ratings ÷ bids
        good = round((ratings >= GOOD_MIN).mean() * 100, 1) if n else 0.0
        poor = round((ratings <= POOR_MAX).mean() * 100, 1) if n else 0.0
        rows.append({
            "period": per.to_timestamp(),
            "bids": bids, "rated": n,
            "promoters": prom, "passives": pas, "detractors": det,
            "nps": nps, "avg_rating": avg,
            "ratings_conv_pct": conv, "pct_good": good, "pct_poor": poor,
        })

    out = pd.DataFrame(rows).sort_values("period").reset_index(drop=True)
    out["nps_delta"] = out["nps"].diff().round(1)
    out["avg_rating_delta"] = out["avg_rating"].diff().round(2)
    return out


def by_jobtype(df, freq="W"):
    """NPS + average rating per job type for the latest period vs the previous one
    (the 'Rating vs Job Type — WoW' tab). Ranked worst-NPS first = act here."""
    d = df.copy()
    d[DATE_COL] = pd.to_datetime(d[DATE_COL], errors="coerce")
    d = d.dropna(subset=[DATE_COL])
    if d.empty or JOB_COL not in d.columns:
        return pd.DataFrame()
    d["period"] = d[DATE_COL].dt.to_period(freq)
    periods = sorted(d["period"].unique())
    if not periods:
        return pd.DataFrame()
    last = periods[-1]
    prev = periods[-2] if len(periods) >= 2 else None

    def nps_per(sub):
        res = {}
        for jt, g in sub.groupby(JOB_COL):
            r = pd.to_numeric(g[RATING_COL], errors="coerce").dropna()
            _, _, _, n, nps = _counts(r)
            res[jt] = (nps, round(float(r.mean()), 2) if n else np.nan, n)
        return res

    cur = nps_per(d[d["period"] == last])
    pre = nps_per(d[d["period"] == prev]) if prev is not None else {}

    rows = []
    for jt, (nps, avg, n) in cur.items():
        prev_nps = pre.get(jt, (None,))[0]
        rows.append({
            "job_type": jt, "nps": nps, "avg_rating": avg, "rated": n,
            "nps_delta": round(nps - prev_nps, 1) if prev_nps is not None else None,
        })
    return pd.DataFrame(rows).sort_values("nps").reset_index(drop=True)


def headline(weekly):
    """One-line summary of the latest week — the punchline above the grid."""
    if weekly is None or len(weekly) == 0:
        return "No ratings data to track."
    last = weekly.iloc[-1]
    delta = last["nps_delta"] if pd.notna(last["nps_delta"]) else 0.0
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "→")
    return (f"Latest-week NPS **{last['nps']:.0f}** ({arrow}{abs(delta):.0f} WoW) · "
            f"avg rating **{last['avg_rating']:.2f}** · "
            f"**{last['rated']} of {last['bids']}** jobs rated "
            f"({last['ratings_conv_pct']:.0f}% conversion).")


def display_grid(weekly, n_periods=12):
    """Transpose to the company layout: metrics as rows, recent periods as columns
    (most recent first) — so it reads like the spreadsheet they hand-build."""
    if weekly is None or len(weekly) == 0:
        return pd.DataFrame()
    w = weekly.tail(n_periods).copy()
    w["label"] = w["period"].dt.strftime("%d %b")
    show = w.set_index("label")[[
        "nps", "avg_rating", "promoters", "passives", "detractors",
        "rated", "bids", "ratings_conv_pct", "pct_good", "pct_poor",
    ]]
    grid = show.T
    grid.index = ["NPS", "Avg rating", "Promoters", "Passives", "Detractors",
                  "Total ratings", "Total bids", "Ratings conv. %",
                  "% good (5★)", "% poor (≤3★)"]
    return grid[grid.columns[::-1]]   # most recent week first


def to_excel_bytes(weekly, monthly, jobtype):
    """The whole tracker as a multi-tab .xlsx — the deliverable that replaces the
    hand-built sheet. Returns bytes (None if there's nothing to write)."""
    import io
    frames = [("Weekly (WTD)", weekly), ("Monthly (MoM)", monthly),
              ("By job type (WoW)", jobtype)]
    frames = [(n, f) for n, f in frames if f is not None and len(f)]
    if not frames:
        return None
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        for name, f in frames:
            f.to_excel(xl, sheet_name=name[:31], index=False)
    return buf.getvalue()
