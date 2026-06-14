"""
auto.py — universal auto-analysis for ANY table (unknown rows/columns).

The BD Action Center is domain-specific (it needs marketplace bookings columns).
Everything else is made universal here: drop in any sheet and this profiles the
columns, builds sensible KPIs + charts, and writes a plain-English summary — with
hard guards so it never blows up on weird data (high-cardinality ids, all-null
columns, free text). The flexible Q&A (llm.ask_table) + chart-from-question
(charts.dynamic_chart) sit on top, so the user can also ask anything.
"""

import re
import warnings

import numpy as np
import pandas as pd
import plotly.express as px

from charts import PALETTE, LAYOUT

MAX_CAT = 30      # a categorical with more groups than this is charted as Top-N only
TOP_N = 12
_ACCENT = "#2563eb"
_ACCENT2 = "#7c3aed"

# a column NAME that looks like an identifier (so a unique-valued measure like
# "salary" or "deal_size" isn't mistaken for an id just because values are unique)
_ID_NAME = re.compile(r"(^|[_\s])(id|ids|code|key|uuid|guid|ref|no|num|number|"
                      r"phone|mobile|pin|zip|sku|account|invoice)($|[_\s])", re.I)
_DATE_HINT = re.compile(r"[-/:]|\d{4}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec", re.I)


# ----------------------------------------------------------------------------
# profiling
# ----------------------------------------------------------------------------
def _is_sequential(s):
    """True if the (sorted) unique values step by a constant ≠ 0 — i.e. a row index."""
    vals = pd.to_numeric(s, errors="coerce").dropna().unique()
    if len(vals) < 3:
        return False
    diffs = np.diff(np.sort(vals))
    return bool(len(diffs) and np.all(diffs == diffs[0]) and diffs[0] != 0)


def _is_datetime_like(s):
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if pd.api.types.is_numeric_dtype(s):
        return False
    sample = s.dropna().astype(str).head(50)
    if len(sample) == 0 or not sample.str.contains(_DATE_HINT, regex=True).any():
        return False     # cheap pre-filter avoids parsing 'North'/'Open' (and its warning)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce")
    return parsed.notna().mean() >= 0.8


def profile(df):
    """Classify every column → numeric / categorical / datetime / id_like / text.
    Returns a dict of lists. Pure, cheap, and never raises on odd data."""
    out = {"numeric": [], "categorical": [], "datetime": [], "id_like": [], "text": []}
    n = len(df)
    for c in df.columns:
        s = df[c]
        nun = int(s.nunique(dropna=True))
        if pd.api.types.is_numeric_dtype(s):
            # only an id if the NAME says so or values are a perfect sequence —
            # a unique-valued measure (salary, deal_size) stays a numeric measure
            if n and nun == n and (_ID_NAME.search(str(c)) or _is_sequential(s)):
                out["id_like"].append(c)
            else:
                out["numeric"].append(c)
        elif _is_datetime_like(s):
            out["datetime"].append(c)
        elif n and nun == n:
            out["id_like"].append(c)              # every value unique → an id/code
        elif nun <= MAX_CAT:
            out["categorical"].append(c)
        elif nun / max(n, 1) > 0.6:
            out["text"].append(c)                 # mostly-unique free text
        else:
            out["categorical"].append(c)          # mid-cardinality → still groupable (Top-N)
    return out


def _short(v):
    try:
        v = float(v)
    except Exception:
        return str(v)
    a = abs(v)
    if a >= 1e9:
        return f"{v/1e9:.1f}B"
    if a >= 1e6:
        return f"{v/1e6:.1f}M"
    if a >= 1e3:
        return f"{v/1e3:.1f}K"
    return f"{v:,.0f}" if v == int(v) else f"{v:,.1f}"


def kpis(df, prof):
    """A small KPI row that makes sense for any table."""
    items = [("Rows", f"{len(df):,}"), ("Columns", str(df.shape[1]))]
    if prof["datetime"]:
        d = pd.to_datetime(df[prof["datetime"][0]], errors="coerce").dropna()
        if len(d):
            items.append(("Date range", f"{d.min():%d %b %y} – {d.max():%d %b %y}"))
    for c in prof["numeric"][:2]:
        items.append((f"Σ {c}"[:22], _short(pd.to_numeric(df[c], errors="coerce").sum())))
    if prof["categorical"]:
        c = prof["categorical"][0]
        items.append((f"Distinct {c}"[:22], f"{df[c].nunique():,}"))
    return items[:6]


def summary(df, prof):
    """Plain-English description of an arbitrary dataset (deterministic, offline)."""
    parts = [f"**{len(df):,} rows × {df.shape[1]} columns.**"]
    if prof["datetime"]:
        d = pd.to_datetime(df[prof["datetime"][0]], errors="coerce").dropna()
        if len(d):
            parts.append(f"Spans **{d.min():%d %b %Y} → {d.max():%d %b %Y}**.")
    if prof["categorical"]:
        c = prof["categorical"][0]
        vc = df[c].value_counts()
        if len(vc):
            parts.append(f"Most common **{c}**: {vc.index[0]} ({vc.iloc[0]:,} rows).")
    if prof["numeric"]:
        c = prof["numeric"][0]
        s = pd.to_numeric(df[c], errors="coerce")
        parts.append(f"**{c}** totals {_short(s.sum())} (avg {_short(s.mean())}).")
    parts.append(f"_Detected {len(prof['numeric'])} numeric, "
                 f"{len(prof['categorical'])} categorical, "
                 f"{len(prof['datetime'])} date column(s)._")
    return " ".join(parts)


# ----------------------------------------------------------------------------
# auto charts (each builder is guarded → returns None when it can't make sense)
# ----------------------------------------------------------------------------
def _trend(df, dcol, ncol):
    d = df.copy()
    d[dcol] = pd.to_datetime(d[dcol], errors="coerce")
    d = d.dropna(subset=[dcol])
    if len(d) < 2:
        return None
    span = (d[dcol].max() - d[dcol].min()).days
    freq = "D" if span <= 60 else ("W" if span <= 540 else "M")
    d["p"] = d[dcol].dt.to_period(freq).dt.to_timestamp()
    if ncol:
        g = pd.to_numeric(d[ncol], errors="coerce").groupby(d["p"]).sum()
        name = f"Σ {ncol}"
    else:
        g = d.groupby("p").size()
        name = "Records"
    if len(g) < 2:
        return None
    fig = px.line(x=g.index, y=g.values, markers=True,
                  title=f"{name} over time", color_discrete_sequence=[_ACCENT])
    fig.update_layout(**LAYOUT)
    fig.update_xaxes(title="")
    fig.update_yaxes(title=name)
    return fig


def _cat_bar(df, ccol, ncol):
    if ncol:
        g = (pd.to_numeric(df[ncol], errors="coerce").groupby(df[ccol]).sum()
             .sort_values(ascending=False).head(TOP_N))
        title, xlab = f"Top {ccol} by Σ {ncol}", f"Σ {ncol}"
    else:
        g = df.groupby(ccol).size().sort_values(ascending=False).head(TOP_N)
        title, xlab = f"Top {ccol} by count", "Count"
    g = g.dropna()
    if len(g) == 0:
        return None
    fig = px.bar(x=g.values, y=[str(i) for i in g.index], orientation="h",
                 title=title, color_discrete_sequence=[_ACCENT])
    fig.update_layout(**LAYOUT)
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(title=xlab)
    return fig


def _cat_pie(df, ccol):
    g = df.groupby(ccol).size().sort_values(ascending=False).head(TOP_N)
    if len(g) < 2:
        return None
    fig = px.pie(names=[str(i) for i in g.index], values=g.values,
                 title=f"{ccol} share", color_discrete_sequence=PALETTE)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(**LAYOUT)
    return fig


def _hist(df, ncol):
    s = pd.to_numeric(df[ncol], errors="coerce").dropna()
    if len(s) < 2:
        return None
    fig = px.histogram(x=s, nbins=min(30, max(5, int(len(s) ** 0.5))),
                       title=f"Distribution of {ncol}", color_discrete_sequence=[_ACCENT2])
    fig.update_layout(**LAYOUT)
    fig.update_xaxes(title=ncol)
    fig.update_yaxes(title="Count")
    return fig


def auto_figs(df, prof):
    """Pick a handful of sensible charts for any dataset. Always returns a list
    (possibly empty); each entry is a ready plotly figure."""
    figs = []
    num, cat, dt = prof["numeric"], prof["categorical"], prof["datetime"]
    if dt:
        figs.append(_trend(df, dt[0], num[0] if num else None))
    if cat:
        figs.append(_cat_bar(df, cat[0], num[0] if num else None))
        figs.append(_cat_pie(df, cat[0]))
    if len(cat) > 1:
        figs.append(_cat_bar(df, cat[1], num[0] if num else None))
    elif num:
        figs.append(_hist(df, num[0]))
    return [f for f in figs if f is not None]
