"""
app.py — BD Performance & Action Report (Streamlit).

Layout = headline on top, evidence below:
  KPI row -> ACTION CENTER (memo + recruitment table + alerts) -> download deck
  -> charts -> next-week outlook -> churn risk -> ask-anything chat.
The whole report renders WITHOUT the LLM (every call has a fallback). A prominent
timer shows "Report generated in Xs" — the punchline.

Run:  streamlit run app.py
"""

import json
import os
import time

import pandas as pd
import streamlit as st

import insights
import charts
import llm
from ingest import load_and_merge, load_samples
from export import build_pptx, build_pdf

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SAMPLE_FILES = {
    "Bookings": "sample_bookings.xlsx",
    "Partners": "sample_partners.xlsx",
    "Leads": "sample_leads.xlsx",
}


@st.cache_data(show_spinner=False)
def _sample_bytes(filename):
    """Read a bundled sample file once, then serve from cache (keeps deploy light)."""
    with open(os.path.join(DATA_DIR, filename), "rb") as f:
        return f.read()

st.set_page_config(page_title="BD Action Report", page_icon="📊", layout="wide")

# ----------------------------------------------------------------------------
# styling
# ----------------------------------------------------------------------------
st.markdown("""
<style>
    .block-container {padding-top: 2rem;}
    .kpi-card {background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;
               padding:14px 18px;text-align:center;}
    .kpi-val {font-size:26px;font-weight:700;color:#2563eb;}
    .kpi-risk {color:#dc2626 !important;}
    .kpi-lbl {font-size:13px;color:#64748b;}
    .timer {background:#dcfce7;color:#166534;font-weight:700;padding:8px 16px;
            border-radius:8px;display:inline-block;font-size:18px;}
    .alert-high {background:#fef2f2;border-left:4px solid #dc2626;padding:8px 12px;
                 border-radius:6px;margin:4px 0;}
    .alert-med {background:#fffbeb;border-left:4px solid #f59e0b;padding:8px 12px;
                border-radius:6px;margin:4px 0;}
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# session state
# ----------------------------------------------------------------------------
def _init():
    for k, v in {
        "data": None, "merge_log": None, "report": None,
        "load_time": None, "chat_history": [],
        "gs_url": "", "gs_creds": None,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init()


def _get_service_account():
    """Service-account creds from st.secrets, else None (UI offers a JSON upload)."""
    try:
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass
    return None


def _cleaned_xlsx_bytes(data):
    """The exact CLEANED tables, as a multi-sheet .xlsx — so any number the app
    reports can be reproduced in Excel (e.g. SUMIFS) to the rupee."""
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name in ("bookings", "partners", "leads"):
            df = data.get(name)
            if df is not None and len(df):
                df.to_excel(w, sheet_name=name, index=False)
    return buf.getvalue()


def _run_report(data):
    """Compute everything once; cache in session_state. Returns elapsed seconds."""
    t0 = time.time()
    bookings = data["bookings"]
    partners = data.get("partners")

    kpis = insights.kpi_summary(bookings, partners)
    gap = insights.demand_supply_gap(bookings, partners)
    alerts = insights.anomalies(bookings)
    figs = charts.build_all(bookings, partners)
    memo = llm.action_memo(kpis, gap, alerts)
    fc = insights.forecast(bookings)
    targets = insights.suggested_targets(bookings)
    churn = insights.churn_risk(partners, bookings)

    elapsed = time.time() - t0
    st.session_state.report = {
        "kpis": kpis, "gap": gap, "alerts": alerts, "figs": figs,
        "memo": memo, "forecast": fc, "targets": targets, "churn": churn,
        "headline": insights.gap_headline(gap), "elapsed": elapsed,
    }
    return elapsed


# ----------------------------------------------------------------------------
# header
# ----------------------------------------------------------------------------
st.title("📊 BD Performance & Action Report — Automated")
st.caption("What takes a BD analyst ~3 hours every Monday — clean, merge, chart, "
           "and decide — done in seconds. The product is **decisions, not dashboards.**")

llm_on = llm.llm_available()
st.caption(f"LLM polish: {'🟢 Groq connected' if llm_on else '⚪ offline — full report still renders via fallbacks'}")

# ----------------------------------------------------------------------------
# data controls
# ----------------------------------------------------------------------------
c1, c2 = st.columns([2, 1])
with c1:
    uploaded = st.file_uploader(
        "Drop raw exports (bookings, partners, leads — any order, csv/xlsx)",
        type=["xlsx", "csv"], accept_multiple_files=True,
    )
with c2:
    st.write("")
    st.write("")
    load_sample = st.button("⚡ Load sample data", type="primary", use_container_width=True)

with st.expander("📁 Or download the sample (dummy) data — try the upload flow yourself"):
    st.caption("Realistic, deliberately-messy exports (mixed spellings, dupes, bad values). "
               "Download, then drag them into the uploader above.")
    dcols = st.columns(len(SAMPLE_FILES))
    for col, (label, fname) in zip(dcols, SAMPLE_FILES.items()):
        try:
            col.download_button(
                f"⬇️ {label}", data=_sample_bytes(fname), file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except FileNotFoundError:
            col.caption(f"{label}: run `data_generator.py`")

if load_sample:
    try:
        t0 = time.time()
        data, mlog = load_samples()
        st.session_state.data = data
        st.session_state.merge_log = mlog
        st.session_state.load_time = time.time() - t0
        st.session_state.report = None
    except FileNotFoundError:
        st.error("Sample data not found. Run `python data_generator.py` first to create the data/ files.")

if uploaded:
    t0 = time.time()
    data, mlog = load_and_merge(uploaded)
    st.session_state.data = data
    st.session_state.merge_log = mlog
    st.session_state.load_time = time.time() - t0
    st.session_state.report = None


# ----------------------------------------------------------------------------
# Google Sheets (read raw data from / write report back to a private sheet)
# ----------------------------------------------------------------------------
with st.expander("🔗 Connect a Google Sheet (read data live · write the report back)"):
    st.caption("Your data already lives in a shared sheet — connect to it, run the "
               "report, and push the Action Center back to a **BD Report** tab. "
               "(Local **Load sample data** above stays the offline fallback.)")
    gs_url = st.text_input("Google Sheet URL or key", value=st.session_state.gs_url,
                           placeholder="https://docs.google.com/spreadsheets/d/.../edit")

    creds = _get_service_account()
    if creds:
        st.success("Service-account credentials loaded from `.streamlit/secrets.toml`.")
    else:
        up_json = st.file_uploader("Service-account JSON key", type="json", key="sa_json")
        if up_json is not None:
            try:
                creds = json.load(up_json)
            except Exception as e:
                st.error(f"Couldn't read JSON key: {e}")

    if creds:
        try:
            import gsheets
            st.caption(f"📧 Share your sheet (Editor) with: "
                       f"`{gsheets.service_account_email(creds)}`")
        except Exception:
            pass

    gcol1, gcol2 = st.columns(2)
    read_clicked = gcol1.button("📥 Read from Sheet & build report", use_container_width=True,
                                disabled=not (gs_url and creds))
    write_clicked = gcol2.button("📤 Write report back to Sheet", use_container_width=True,
                                 disabled=not (gs_url and creds and st.session_state.report))

    if read_clicked:
        try:
            import gsheets
            with st.spinner("Reading Google Sheet, cleaning & merging..."):
                t0 = time.time()
                client = gsheets.connect(creds)
                data, mlog = gsheets.load_from_gsheet(client, gs_url)
                st.session_state.data = data
                st.session_state.merge_log = mlog
                st.session_state.load_time = time.time() - t0
                st.session_state.report = None
                st.session_state.gs_url = gs_url
                st.session_state.gs_creds = creds
            st.success("Loaded from Google Sheets — scroll down and Generate Report.")
        except Exception as e:
            st.error(f"Could not read the sheet: {e}\n\nCheck the URL, that the "
                     f"service account has access, and that the Sheets API is enabled.")

    if write_clicked:
        try:
            import gsheets
            from datetime import datetime
            with st.spinner("Writing the BD Report tab..."):
                client = gsheets.connect(creds)
                rep = st.session_state.report
                link = gsheets.write_report(
                    client, gs_url, rep["kpis"], rep["gap"], rep["alerts"], rep["memo"],
                    generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                )
            st.success("Report written to the **BD Report** tab.")
            st.markdown(f"[Open the report tab]({link})")
        except Exception as e:
            st.error(f"Could not write to the sheet: {e}")


# ----------------------------------------------------------------------------
# merge + cleaning logs
# ----------------------------------------------------------------------------
if st.session_state.merge_log:
    mlog = st.session_state.merge_log
    st.success(f"✅ {mlog['summary']}  (ingested in {st.session_state.load_time:.2f}s)")
    with st.expander("🔍 Merge & cleaning log — proof the grind was automated", expanded=True):
        lc, rc = st.columns(2)
        with lc:
            st.markdown("**Files auto-detected & merged**")
            for d in mlog["detected"]:
                st.write(f"- {d}")
            if mlog.get("bookings_enriched"):
                st.write(f"- 🔗 {mlog['bookings_enriched']:,} bookings enriched with partner data (the VLOOKUP grind)")
        with rc:
            clog = mlog.get("cleaning", {}).get("bookings", {})
            if clog:
                st.markdown("**Bookings cleaning**")
                st.write(f"- Rows in → out: {clog.get('rows_in', 0):,} → {clog.get('rows_out', 0):,}")
                st.write(f"- Duplicate bookings removed: **{clog.get('duplicates_removed', 0)}**")
                st.write(f"- City spellings standardized: **{clog.get('cities_standardized', 0)}**")
                st.write(f"- Category spellings standardized: **{clog.get('categories_standardized', 0)}**")
                st.write(f"- Invalid ₹ values fixed: **{clog.get('invalid_values_fixed', 0)}**")
                st.write(f"- Blank city/category handled: **{clog.get('blank_city_or_category', 0)}**")

        st.download_button(
            "⬇️ Download CLEANED data (.xlsx) — verify any number in Excel",
            data=_cleaned_xlsx_bytes(st.session_state.data),
            file_name="cleaned_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="This is the exact dataset the app and chat query. "
                 "Run e.g. =SUMIFS(H:H, C:C, \"Mumbai\", J:J, \"completed\") to match revenue.",
        )

    gen = st.button("🚀 Generate Report", type="primary", use_container_width=True)
    if gen or st.session_state.report:
        if not st.session_state.report:
            with st.spinner("Cleaning done — running decision engine, charts & memo..."):
                _run_report(st.session_state.data)


# ----------------------------------------------------------------------------
# report
# ----------------------------------------------------------------------------
rep = st.session_state.report
if rep:
    st.markdown(f"<div class='timer'>⚡ Report generated in {rep['elapsed']:.1f}s "
                f"— an analyst's ~3-hour Monday, automated.</div>", unsafe_allow_html=True)
    st.write("")

    # ---- KPI row ----
    k = rep["kpis"]
    cols = st.columns(6)
    kpi_items = [
        ("GMV", insights.inr(k["gmv"]), False),
        ("Bookings", f"{k['total_bookings']:,}", False),
        ("AOV", insights.inr(k["aov"]), False),
        ("Active partners", str(k["active_partners"]), False),
        ("Completion", f"{k['completion_rate']*100:.0f}%", False),
        ("₹/week at risk", insights.inr(k["revenue_at_risk_per_week"]), True),
    ]
    for col, (lbl, val, risk) in zip(cols, kpi_items):
        cls = "kpi-val kpi-risk" if risk else "kpi-val"
        col.markdown(f"<div class='kpi-card'><div class='{cls}'>{val}</div>"
                     f"<div class='kpi-lbl'>{lbl}</div></div>", unsafe_allow_html=True)

    st.write("")
    st.divider()

    # ---- ACTION CENTER (headline) ----
    st.header("🎯 Action Center")
    st.markdown(f"### {rep['headline']}")

    ac_l, ac_r = st.columns([3, 2])
    with ac_l:
        st.markdown("#### Leadership memo")
        st.markdown(rep["memo"])

        st.markdown("#### 📋 Recommended recruitment — ranked by ₹ at risk")
        gap = rep["gap"]
        under = gap[gap["gap_flag"] == "UNDERSUPPLIED"] if len(gap) else gap
        if under is not None and len(under):
            show = under[["city", "service_category", "active_partners",
                          "cancel_rate", "wow_growth", "recommended_partner_adds",
                          "est_revenue_at_risk_per_week"]].copy()
            show["cancel_rate"] = (show["cancel_rate"] * 100).round(0).astype(int).astype(str) + "%"
            show["wow_growth"] = (show["wow_growth"] * 100).round(0).astype(int).map(lambda x: f"{x:+d}%")
            show["est_revenue_at_risk_per_week"] = show["est_revenue_at_risk_per_week"].map(insights.inr)
            show.columns = ["City", "Category", "Active", "Cancel%", "WoW", "Recruit", "₹/wk at risk"]
            st.dataframe(show, use_container_width=True, hide_index=True)
        else:
            st.info("No critical undersupply this week — supply is broadly balanced.")

    with ac_r:
        st.markdown("#### 🚨 Alerts")
        if rep["alerts"]:
            for a in rep["alerts"][:10]:
                cls = "alert-high" if a["severity"] == "high" else "alert-med"
                icon = "🔴" if a["severity"] == "high" else "🟠"
                st.markdown(f"<div class='{cls}'>{icon} {a['text']}</div>", unsafe_allow_html=True)
        else:
            st.success("No anomalies beyond thresholds this week.")

    # ---- download deck ----
    st.write("")
    dl_l, dl_r = st.columns(2)
    with dl_l:
        try:
            pptx_bytes = build_pptx(rep["kpis"], rep["memo"], rep["gap"],
                                    rep["alerts"], rep["figs"])
            st.download_button("📥 Download leadership deck (.pptx)", data=pptx_bytes,
                               file_name="BD_Monday_Report.pptx", use_container_width=True,
                               mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
        except Exception as e:
            st.warning(f"Deck export unavailable ({e})")
    with dl_r:
        pdf_bytes = build_pdf(rep["kpis"], rep["memo"], rep["gap"], rep["alerts"])
        if pdf_bytes:
            st.download_button("📄 Download memo (.pdf)", data=pdf_bytes,
                               file_name="BD_Monday_Memo.pdf", use_container_width=True,
                               mime="application/pdf")

    st.divider()

    # ---- charts ----
    st.header("📈 Supporting evidence")
    figs = rep["figs"]
    g1c1, g1c2 = st.columns(2)
    g1c1.plotly_chart(figs["demand_supply"], use_container_width=True)
    g1c2.plotly_chart(figs["wow_trend"], use_container_width=True)
    g2c1, g2c2 = st.columns(2)
    g2c1.plotly_chart(figs["revenue_by_city"], use_container_width=True)
    g2c2.plotly_chart(figs["revenue_by_category"], use_container_width=True)
    g3c1, g3c2 = st.columns(2)
    g3c1.plotly_chart(figs["bookings_by_city"], use_container_width=True)
    g3c2.plotly_chart(figs["top_aov"], use_container_width=True)
    g4c1, g4c2 = st.columns(2)
    g4c1.plotly_chart(figs["onboarding_funnel"], use_container_width=True)
    g4c2.plotly_chart(figs["status_by_category"], use_container_width=True)

    st.divider()

    # ---- next-week outlook ----
    st.header("🔮 Next-week outlook")
    fc = rep["forecast"]["overall"]
    tg = rep["targets"]
    o1, o2, o3 = st.columns(3)
    o1.metric("Forecast bookings (next wk)", f"{fc.get('next_week_bookings', 0):,}")
    o2.metric("Forecast revenue (next wk)", insights.inr(fc.get("next_week_revenue", 0)))
    o3.metric("Suggested revenue target (+5%)", insights.inr(tg.get("target_revenue", 0)))
    st.caption(f"Method: {fc.get('method', '')}.")
    if tg.get("cities_below_trend"):
        st.warning("Cities tracking below trend: " + ", ".join(tg["cities_below_trend"]))

    st.divider()

    # ---- churn risk ----
    churn = rep["churn"]
    st.header("⚠️ Partner churn risk")
    if churn["count"]:
        st.markdown(f"**{churn['count']} active partners at churn risk** "
                    f"(jobs down >40% over 3 weeks AND low rating or idle).")
        by_city = ", ".join(f"{c} ({n})" for c, n in list(churn["by_city"].items())[:6])
        st.write("By city: " + by_city)
        with st.expander("View at-risk partners"):
            st.dataframe(pd.DataFrame(churn["partners"]), use_container_width=True, hide_index=True)
    else:
        st.success("No partners flagged at churn risk this week.")

    st.divider()

    # ---- ask-anything chat ----
    st.header("💬 Ask anything")
    st.caption("Ad-hoc Q&A over the data — like pinging the analyst, e.g. "
               "*'revenue by city'*, *'AC Service cancellations'*, *'bookings trend'*.")

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("df") is not None:
                st.dataframe(msg["df"], use_container_width=True)

    q = st.chat_input("Ask about revenue, bookings, AOV, ratings, cancellations...")
    if q:
        st.session_state.chat_history.append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)
        answer, df, _intent = llm.chat_answer(q, st.session_state.data["bookings"])
        with st.chat_message("assistant"):
            st.markdown(answer)
            if df is not None and len(df):
                st.dataframe(df, use_container_width=True)
        st.session_state.chat_history.append(
            {"role": "assistant", "content": answer, "df": df if df is not None else None}
        )

else:
    st.info("👆 Click **Load sample data** (or upload your exports) to begin, "
            "then **Generate Report**.")
