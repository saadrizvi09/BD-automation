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
        '"group_by": column or null, "filter": {column: value} or {}, '
        '"chart_type": one of [bar,line,none]}.\n'
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

    # filter by known city / category values present in the data
    for city in bookings["city"].dropna().unique():
        if city.lower() in q:
            intent["filter"]["city"] = city
    for cat in bookings["service_category"].dropna().unique():
        if cat.lower() in q or cat.lower().replace(" & ", " and ") in q:
            intent["filter"]["service_category"] = cat

    # group-by detection
    if "by city" in q or "per city" in q or "each city" in q:
        intent["group_by"] = "city"
    elif "by category" in q or "per category" in q or "by service" in q:
        intent["group_by"] = "service_category"
    elif "by week" in q or "trend" in q or "over time" in q:
        intent["group_by"] = "week"
        intent["chart_type"] = "line"
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
