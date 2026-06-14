"""
llm.py — Groq integration with a hard guarantee: every function works offline.

Model: llama-3.3-70b-versatile. Key from GROQ_API_KEY. We NEVER send raw rows —
only schemas, lists of unique messy strings, or computed aggregates. Every call
is wrapped in try/except and silently falls back to deterministic logic, so the
demo never blocks on the network or a rate limit.
"""

import json
import os
import re

import pandas as pd

from insights import inr, _inr_short

MODEL = "llama-3.3-70b-versatile"


def _get_groq_key():
    """GROQ key from env var (local dev) or st.secrets (Streamlit Cloud deploy).

    Checks the env var first so local runs don't touch st.secrets; falls back to
    st.secrets["GROQ_API_KEY"] for the deployed app, where there's no shell to
    export env vars. Wrapped in try/except so a missing secrets file is harmless.
    """
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
    except Exception:
        pass
    return None


def _client():
    key = _get_groq_key()
    if not key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=key)
    except Exception:
        return None


def _chat(messages, max_tokens=900, temperature=0.3):
    """Low-level call; returns text or None on any failure."""
    client = _client()
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        return resp.choices[0].message.content
    except Exception:
        return None


def llm_available():
    return _client() is not None


# ----------------------------------------------------------------------------
# 1. Action memo (headline artifact — must ALWAYS exist)
# ----------------------------------------------------------------------------
def action_memo(kpis, gap_table, alerts):
    """Send NUMBERS ONLY. Falls back to a templated memo from the same numbers."""
    top_gaps = []
    if gap_table is not None and len(gap_table):
        und = gap_table[gap_table["gap_flag"] == "UNDERSUPPLIED"].head(5)
        for _, r in und.iterrows():
            top_gaps.append({
                "city": r["city"], "category": r["service_category"],
                "recruit": int(r["recommended_partner_adds"]),
                "active_partners": int(r["active_partners"]),
                "cancel_rate_pct": round(r["cancel_rate"] * 100, 1),
                "wow_growth_pct": round(r["wow_growth"] * 100, 1),
                "risk_per_week_inr": round(r["est_revenue_at_risk_per_week"]),
            })

    payload = {
        "kpis": {
            "gmv_inr": round(kpis["gmv"]),
            "total_bookings": kpis["total_bookings"],
            "aov_inr": round(kpis["aov"]),
            "active_partners": kpis["active_partners"],
            "completion_rate_pct": round(kpis["completion_rate"] * 100, 1),
            "revenue_at_risk_per_week_inr": round(kpis["revenue_at_risk_per_week"]),
        },
        "undersupplied_cells": top_gaps,
        "alerts": [a["text"] for a in (alerts or [])[:8]],
    }

    prompt = (
        "You are a senior marketplace BD analyst writing a one-page Monday memo "
        "for leadership. Using ONLY the JSON numbers below, write a crisp memo with "
        "these sections: **Top 3 Problems**, **Top 3 Opportunities**, "
        "**Recommended Actions** (specific: city, category, partners to recruit), and "
        "**Total ₹ Impact**. Be concrete and use the rupee figures. No preamble.\n\n"
        f"DATA:\n{json.dumps(payload, indent=2)}"
    )
    text = _chat([{"role": "user", "content": prompt}], max_tokens=900)
    if text:
        return text.strip()
    return _memo_fallback(payload)


def _memo_fallback(payload):
    k = payload["kpis"]
    gaps = payload["undersupplied_cells"]
    alerts = payload["alerts"]
    total_risk = k["revenue_at_risk_per_week_inr"]

    lines = []
    lines.append("### Monday BD Action Memo\n")
    lines.append("**Top 3 Problems**")
    probs = []
    for g in gaps[:3]:
        probs.append(
            f"- Undersupply in **{g['category']} — {g['city']}**: only "
            f"{g['active_partners']} active partners, {g['cancel_rate_pct']:.0f}% cancellations, "
            f"~{inr(g['risk_per_week_inr'])}/week leaking."
        )
    if not probs:
        probs.append("- No critical undersupply detected this week.")
    for a in alerts[:max(0, 3 - len(probs))]:
        probs.append(f"- {a}")
    lines += probs

    lines.append("\n**Top 3 Opportunities**")
    if gaps:
        for g in gaps[:3]:
            lines.append(
                f"- Capture ~{inr(g['risk_per_week_inr'])}/week by recruiting "
                f"~{g['recruit']} partners for {g['category']} in {g['city']} "
                f"(demand {g['wow_growth_pct']:+.0f}% WoW)."
            )
    else:
        lines.append("- Reallocate oversupplied partners toward high-growth cells.")

    lines.append("\n**Recommended Actions**")
    if gaps:
        for g in gaps:
            lines.append(
                f"- Recruit **{g['recruit']} partners** → {g['category']}, {g['city']} "
                f"(protects ~{inr(g['risk_per_week_inr'])}/week)."
            )
    else:
        lines.append("- Maintain current supply; monitor alerts below.")

    lines.append(f"\n**Total ₹ Impact:** ~{inr(total_risk)}/week recoverable "
                 f"(≈ {inr(total_risk*52)}/year) by closing the supply gaps above.")
    lines.append(f"\n_KPIs: GMV {inr(k['gmv_inr'])} · {k['total_bookings']:,} bookings · "
                 f"AOV {inr(k['aov_inr'])} · {k['active_partners']} active partners · "
                 f"{k['completion_rate_pct']:.0f}% completion._")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 2. Clean ambiguous values
# ----------------------------------------------------------------------------
def clean_ambiguous(unique_values, target="category"):
    """Map messy strings -> canonical via LLM. Fallback: return {} (cleaning.py maps handle it)."""
    if not unique_values:
        return {}
    canon = ("Salon for Women, Salon for Men, Spa & Massage, Home Deep Cleaning, "
             "Bathroom & Kitchen Cleaning, Sofa & Carpet Cleaning, AC Service & Repair, "
             "Appliance Repair, Plumbing, Electrician, Carpenter, Pest Control, "
             "Painting, RO / Water Purifier") if target == "category" else \
            ("Delhi NCR, Mumbai, Bengaluru, Hyderabad, Pune, Chennai, Kolkata, "
             "Ahmedabad, Jaipur, Chandigarh, Dubai, Singapore")
    prompt = (
        f"Map each messy {target} value to its canonical form. Canonical options: {canon}.\n"
        f"Return ONLY a JSON object mapping input->canonical. Inputs:\n"
        f"{json.dumps(list(unique_values)[:60])}"
    )
    text = _chat([{"role": "user", "content": prompt}], max_tokens=600, temperature=0)
    if not text:
        return {}
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


# ----------------------------------------------------------------------------
# 3 & 4. NL query / chat over the data
# ----------------------------------------------------------------------------
METRICS = {
    "revenue": ("booking_value_inr", "sum"),
    "gmv": ("booking_value_inr", "sum"),
    "bookings": ("booking_id", "count"),
    "count": ("booking_id", "count"),
    "aov": ("booking_value_inr", "mean"),
    "average order value": ("booking_value_inr", "mean"),
    "rating": ("rating", "mean"),
    "cancellations": ("status", "cancel_rate"),
}


def _intent_from_llm(question, schema):
    prompt = (
        "Convert the user's question into a JSON intent for a pandas aggregation over "
        "a bookings table. Schema (columns): " + json.dumps(schema["columns"]) + ". "
        "Sample rows: " + json.dumps(schema["sample"]) + ".\n"
        'Return ONLY JSON: {"metric": one of [revenue,bookings,aov,rating,cancellations], '
        '"group_by": one of [city, service_category, week] or null, '
        '"filter": {column: value} or {}, '
        '"chart_type": one of [pie,bar,line,none]}.\n'
        "Rules: if the user asks for a pie/bar/line chart (or 'share', 'split', "
        "'breakdown', 'distribution'), set chart_type to that AND set a group_by "
        "(city or service_category) so the chart has slices/bars. Use 'line' for "
        "trends over time (group_by=week). Use chart_type 'none' for a single number.\n"
        f"Question: {question}"
    )
    text = _chat([{"role": "user", "content": prompt}], max_tokens=300, temperature=0)
    if not text:
        return None
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def _intent_from_keywords(question, bookings):
    q = question.lower()
    intent = {"metric": "revenue", "group_by": None, "filter": {}, "chart_type": "bar"}

    if "how many" in q or "number of" in q or "count" in q or "bookings" in q:
        intent["metric"] = "bookings"
    if "aov" in q or "average order" in q or "avg order" in q:
        intent["metric"] = "aov"
    if "rating" in q:
        intent["metric"] = "rating"
    if "cancel" in q:
        intent["metric"] = "cancellations"
    if "revenue" in q or "gmv" in q or "sales" in q:
        intent["metric"] = "revenue"

    # chart type the user asked for
    wants_chart = any(w in q for w in (
        "pie", "bar", "line", "chart", "graph", "plot", "trend",
        "breakdown", "distribution", "share", "split", "visual",
    ))
    if "pie" in q or "share" in q or "split" in q or "breakdown" in q or "distribution" in q:
        intent["chart_type"] = "pie"
    elif "line" in q or "trend" in q or "over time" in q:
        intent["chart_type"] = "line"
    else:
        intent["chart_type"] = "bar"

    # filter by known city / category values present in the data
    for city in bookings["city"].dropna().unique():
        if city.lower() in q:
            intent["filter"]["city"] = city
    for cat in bookings["service_category"].dropna().unique():
        if cat.lower() in q or cat.lower().replace(" & ", " and ") in q:
            intent["filter"]["service_category"] = cat

    # group-by detection
    if "by city" in q or "per city" in q or "each city" in q or "across cities" in q:
        intent["group_by"] = "city"
    elif ("by category" in q or "per category" in q or "by service" in q
          or "across categories" in q or "by services" in q):
        intent["group_by"] = "service_category"
    elif "by week" in q or "trend" in q or "over time" in q or "weekly" in q:
        intent["group_by"] = "week"
        intent["chart_type"] = "line"
    elif wants_chart:
        # a chart was requested but no explicit grouping — pick a sensible axis
        intent["group_by"] = "service_category" if intent["filter"] else "city"
    elif not intent["filter"]:
        intent["group_by"] = "city"

    return intent


def run_intent(intent, bookings):
    """Execute the intent in pandas. Returns (answer_text, dataframe_or_None)."""
    df = bookings.copy()
    for col, val in (intent.get("filter") or {}).items():
        if col in df.columns:
            df = df[df[col].astype(str).str.lower() == str(val).lower()]

    metric = intent.get("metric", "revenue")
    gb = intent.get("group_by")

    if metric == "cancellations":
        if gb and gb != "week" and gb in df.columns:
            res = df.groupby(gb).apply(lambda x: (x["status"] == "cancelled").mean() * 100)
            res = res.sort_values(ascending=False).round(1)
            return _phrase(metric, intent, res), res.to_frame("cancel_rate_%")
        rate = (df["status"] == "cancelled").mean() * 100 if len(df) else 0
        return f"Cancellation rate: **{rate:.1f}%**.", None

    col, how = METRICS.get(metric, ("booking_value_inr", "sum"))
    work = df if metric in ("bookings", "count") else df[df["status"] == "completed"]

    if gb == "week":
        from insights import _week_floor
        work = work.copy()
        work["week"] = _week_floor(work["date"])
        res = work.groupby("week")[col].agg(how) if how != "count" else work.groupby("week").size()
        return _phrase(metric, intent, res), res.to_frame(metric)
    if gb and gb in work.columns:
        res = work.groupby(gb)[col].agg(how) if how != "count" else work.groupby(gb).size()
        res = res.sort_values(ascending=False)
        return _phrase(metric, intent, res), res.to_frame(metric)

    # scalar
    val = work[col].agg(how) if how != "count" else len(work)
    return _phrase_scalar(metric, intent, val), None


def _fmt_metric(metric, v):
    if metric in ("revenue", "gmv", "aov"):
        return inr(v)
    if metric == "rating":
        return f"{v:.2f}"
    if metric == "cancellations":
        return f"{v:.1f}%"
    return f"{v:,.0f}"


def _phrase_scalar(metric, intent, val):
    filt = ", ".join(f"{k}={v}" for k, v in (intent.get("filter") or {}).items())
    where = f" for {filt}" if filt else ""
    return f"**{metric.upper()}{where}: {_fmt_metric(metric, val)}**"


def _phrase(metric, intent, series):
    if series is None or len(series) == 0:
        return "No matching data for that question."
    top = series.head(1)
    label, val = top.index[0], top.iloc[0]
    filt = ", ".join(f"{k}={v}" for k, v in (intent.get("filter") or {}).items())
    where = f" ({filt})" if filt else ""
    return (f"Top by {metric}{where}: **{label} = {_fmt_metric(metric, val)}**. "
            f"See the breakdown below.")


def chat_answer(question, bookings, history=None):
    """Schema-only intent (LLM or keyword fallback) -> pandas -> phrased answer + chart df."""
    schema = {
        "columns": list(bookings.columns),
        "sample": bookings.head(3).astype(str).to_dict("records"),
    }
    intent = _intent_from_llm(question, schema) or _intent_from_keywords(question, bookings)
    # guard against a malformed LLM intent
    if not isinstance(intent, dict) or "metric" not in intent:
        intent = _intent_from_keywords(question, bookings)
    try:
        answer, df = run_intent(intent, bookings)
    except Exception:
        answer, df = "I couldn't compute that — try asking about revenue or bookings by city/category.", None
    return answer, df, intent


# convenience alias from the spec
def nl_query(question, bookings):
    return chat_answer(question, bookings)


# ----------------------------------------------------------------------------
# 5. Schema-agnostic Q&A — ask ANY uploaded sheet (not just the bookings table)
#    Privacy: the LLM sees ONLY column names + a few category labels, never rows.
#    It returns a structured intent; OUR pandas code runs the aggregation.
# ----------------------------------------------------------------------------
_AGGS = ("sum", "mean", "count", "min", "max", "median")
_AGG_LABEL = {"sum": "Total", "mean": "Average", "count": "Count",
              "min": "Min", "max": "Max", "median": "Median"}


def table_schema(df, max_uniques=15):
    """Privacy-safe description of an arbitrary table: column names + types + a
    few unique labels for small categoricals. NEVER includes data rows."""
    cols = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            cols.append({"name": str(c), "type": "number"})
        elif pd.api.types.is_datetime64_any_dtype(s):
            cols.append({"name": str(c), "type": "date"})
        else:
            uniq = s.dropna().astype(str).unique()
            info = {"name": str(c), "type": "text", "n_unique": int(len(uniq))}
            info["values" if len(uniq) <= max_uniques else "sample_values"] = list(uniq[:max_uniques])
            cols.append(info)
    return {"columns": cols, "n_rows": int(len(df))}


def _generic_intent_llm(question, schema):
    prompt = (
        "Translate the question into a JSON intent for a pandas aggregation over ONE table. "
        "Use ONLY column names from this schema.\n"
        f"SCHEMA: {json.dumps(schema)}\n"
        'Return ONLY JSON: {"agg": one of [sum,mean,count,min,max,median], '
        '"value_col": a NUMBER column name or null (null = count rows), '
        '"group_by": a column name or null, '
        '"filters": {column: value} using exact values from the schema, or {}, '
        '"chart_type": one of [pie,bar,line,none], '
        '"sort": "desc" or "asc", "top_n": integer or null}\n'
        "Rules: value_col MUST be a number column. For 'how many'/'count' use agg=count, value_col=null. "
        "If a chart/pie/bar/breakdown/trend is requested, set chart_type AND a group_by so it has slices/bars. "
        "Use line for a trend over a date column. Use chart_type 'none' for a single number.\n"
        f"QUESTION: {question}"
    )
    text = _chat([{"role": "user", "content": prompt}], max_tokens=300, temperature=0)
    if not text:
        return None
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def _wb(q, words):
    """Whole-word match — avoids 'pipeline' matching 'line', 'barber' matching 'bar'."""
    return any(re.search(r"\b" + re.escape(w) + r"\b", q) for w in words)


def _generic_intent_keywords(question, df):
    """Offline fallback: infer the intent from the question + the real columns."""
    q = question.lower()
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    dates = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    text_cols = [c for c in df.columns if c not in numeric and c not in dates]

    if _wb(q, ("how many", "number of", "count", "rows")):
        agg, value_col = "count", None
    elif _wb(q, ("average", "avg", "mean")):
        agg, value_col = "mean", None
    elif _wb(q, ("highest", "max", "maximum", "largest", "most", "top")):
        agg, value_col = "max", None
    elif _wb(q, ("lowest", "min", "minimum", "smallest", "least")):
        agg, value_col = "min", None
    else:
        agg, value_col = "sum", None

    # value column: a numeric column named in the question, else the first numeric
    for c in numeric:
        cl = str(c).lower()
        if _wb(q, (cl, cl.replace("_", " "))):
            value_col = c
            break
    if value_col is None and agg != "count" and numeric:
        value_col = numeric[0]

    # group-by: only on an explicit "by/per/each <column>" phrase (a bare column
    # mention is the measure, not the grouping — e.g. "total pipeline value")
    group_by = None
    for c in text_cols + dates:
        cl = str(c).lower().replace("_", " ")
        if any(p in q for p in (f"by {cl}", f"per {cl}", f"each {cl}",
                                f"across {cl}", f"for each {cl}", f"group by {cl}")):
            group_by = c
            break

    # chart type (whole-word so 'pipeline' != 'line', 'barber' != 'bar')
    if _wb(q, ("pie", "share", "split", "breakdown", "distribution", "proportion")):
        chart_type = "pie"
    elif _wb(q, ("line", "trend", "over time", "timeline")):
        chart_type = "line"
        if group_by is None and dates:
            group_by = dates[0]
    elif _wb(q, ("bar", "chart", "graph", "plot", "visual", "compare", "ranking", "rank")):
        chart_type = "bar"
    else:
        chart_type = "none"
    if chart_type != "none" and group_by is None and text_cols:
        group_by = text_cols[0]

    # filter: a categorical value mentioned in the question
    filters = {}
    for c in text_cols:
        for val in df[c].dropna().astype(str).unique()[:300]:
            v = str(val).strip().lower()
            if len(v) >= 3 and v in q:
                filters[c] = val
                break
        if filters:
            break

    return {"agg": agg, "value_col": value_col, "group_by": group_by,
            "filters": filters, "chart_type": chart_type, "sort": "desc", "top_n": None}


def _fmt_num(v):
    try:
        f = float(v)
    except Exception:
        return str(v)
    if pd.isna(f):
        return "n/a"
    if f == int(f):
        return f"{int(f):,}"
    return f"{f:,.2f}"


def run_generic(intent, df):
    """Execute a generic intent in pandas over an arbitrary table.
    Returns (answer_text, result_dataframe_or_None)."""
    work = df.copy()
    for col, val in (intent.get("filters") or {}).items():
        if col in work.columns:
            work = work[work[col].astype(str).str.strip().str.lower() == str(val).strip().lower()]

    agg = (intent.get("agg") or "count").lower()
    if agg not in _AGGS:
        agg = "count"
    value_col = intent.get("value_col")
    if value_col is not None and value_col not in work.columns:
        value_col = None
    gb = intent.get("group_by")
    if gb is not None and gb not in work.columns:
        gb = None

    label = value_col or "rows"
    agg_label = _AGG_LABEL.get(agg, agg.title())

    if gb:
        if agg == "count" or value_col is None:
            res = work.groupby(gb).size()
            colname, label = "count", "rows"
        else:
            num = pd.to_numeric(work[value_col], errors="coerce")
            res = num.groupby(work[gb]).agg(agg)
            colname = f"{agg}_{value_col}"
        res = res.dropna().sort_values(ascending=(intent.get("sort") == "asc"))
        if intent.get("top_n"):
            try:
                res = res.head(int(intent["top_n"]))
            except Exception:
                pass
        if len(res) == 0:
            return "No matching rows for that question.", None
        top_label, top_val = res.index[0], res.iloc[0]
        ans = (f"**{agg_label} of {label} by {gb}** — top: "
               f"**{top_label} = {_fmt_num(top_val)}**. See the breakdown below.")
        return ans, res.to_frame(colname)

    if agg == "count" or value_col is None:
        val = len(work)
        label = "rows"
    else:
        val = pd.to_numeric(work[value_col], errors="coerce").agg(agg)
    filt = ", ".join(f"{k}={v}" for k, v in (intent.get("filters") or {}).items())
    where = f" ({filt})" if filt else ""
    return f"**{agg_label} of {label}{where}: {_fmt_num(val)}**", None


def ask_table(question, df):
    """Schema-agnostic Q&A over any table. Returns (answer, result_df, chart_intent)."""
    schema = table_schema(df)
    intent = _generic_intent_llm(question, schema)
    if not isinstance(intent, dict) or "agg" not in intent:
        intent = _generic_intent_keywords(question, df)
    try:
        answer, res = run_generic(intent, df)
    except Exception:
        answer, res = ("I couldn't compute that — try e.g. 'total <column> by <column>', "
                       "'count by <column>', or 'pie chart of <column> by <column>'."), None
    chart_intent = {
        "group_by": intent.get("group_by"),
        "chart_type": intent.get("chart_type", "none"),
        "metric": intent.get("value_col") or "count",
        "agg": intent.get("agg"),
    }
    return answer, res, chart_intent
