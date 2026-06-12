# BD Performance & Action Report — Automated

Replaces the repetitive 80% of a marketplace BD/ops analyst's week (think Urban
Company): ingest multiple raw exports → auto-merge & clean → **decide what's
broken and what to do, with a ₹ impact** → chart the evidence → answer ad-hoc
questions → export the leadership deck. In seconds.

**The product is decisions, not dashboards.** The headline is the Action Center
(recruitment actions + ₹/week at risk + alerts); the charts are the evidence below.

## Quick start (Windows)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python data_generator.py          # creates data/ sample files (run once)
# optional LLM polish — app works fully without it:
$env:GROQ_API_KEY = "your_key"
streamlit run app.py
```

macOS/Linux: `source venv/bin/activate`, `export GROQ_API_KEY=...`.

## Demo flow
1. **Load sample data** → see the messy table cleaned (merge + cleaning log).
2. **Generate Report** → note the timer (~seconds). Read the **Action Center**:
   undersupplied cells, partners to recruit, ₹/week at risk, red/amber alerts.
3. Scroll to **Supporting evidence** (8 charts), the **next-week outlook**, and
   **churn risk**.
4. **Download leadership deck (.pptx)** — the Monday deliverable in one click.
5. **Ask anything** — ad-hoc Q&A over the data (e.g. "revenue by city").

## Connect to Google Sheets (read data live · write the report back)
The app can read raw data straight from a **private Google Sheet** and write the
finished Action Center back to a **BD Report** tab — using a free Google
service account. Local *Load sample data* / file upload stay as the offline fallback.

**One-time setup (free):**
1. [Google Cloud console](https://console.cloud.google.com/) → new project → enable the **Google Sheets API**.
2. Create a **service account** → **Keys** → add a **JSON** key → download it.
3. Open your Google Sheet → **Share** → add the service account's `client_email` as **Editor**.
4. Put each table on its own tab (detected by columns): a tab with `booking_id`
   (bookings), one with `onboard_date`/`primary_category` (partners), one with
   `lead_id`/`stage` (leads).

**Give it the key** — either:
- copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml` and paste the
  key fields (app auto-loads it), **or**
- just upload the JSON key in the app's "Connect a Google Sheet" panel.

**Use it in the app:** open **🔗 Connect a Google Sheet** → paste the URL →
**📥 Read from Sheet & build report** → **🚀 Generate Report** →
**📤 Write report back to Sheet**.

**Need to populate a test sheet from the sample data first?**
```powershell
python gsheets.py upload --url "<your_sheet_url>" --creds key.json
```
This pushes `sample_bookings/partners/leads` into tabs you can then read back.

> Charts stay as the polished interactive plotly figures in the app; what's written
> back to Sheets is the decision content (KPIs, recruitment table, alerts, memo).
> A live Sheets connection is a network dependency — if conference wifi is shaky,
> demo with *Load sample data* instead.

## How it works (modules)
| File | Role |
|---|---|
| `data_generator.py` | Generates realistic, deliberately-messy sample data with **planted** undersupply cells + anomalies so the Action Center always has something to say. |
| `ingest.py` | Multi-file upload, auto-detect by columns, auto-merge (the VLOOKUP grind). |
| `gsheets.py` | Read raw data from / write the report back to a private Google Sheet (service-account auth). CLI to populate a test sheet. |
| `cleaning.py` | Deterministic cleaning (hardcoded maps + rapidfuzz fallback), robust mixed-date parsing, cleaning log. |
| `insights.py` | **Decision engine** — demand/supply gap, ₹ at risk, anomalies, churn, forecast. Every threshold is a named constant, each rule explainable in one sentence. |
| `charts.py` | 8 polished plotly figures (₹ formatting, sorted bars, % labels). |
| `llm.py` | Groq (memo / cleaning / NL chat) — **every call has a deterministic fallback**, so the app works fully offline. |
| `export.py` | One-click `.pptx` deck (+ optional `.pdf`). Chart images via kaleido with a **hard timeout + probe**, falling back to a clean text+table deck if kaleido is slow/unavailable — the download never hangs. |
| `app.py` | Streamlit UI: Action Center on top, charts below, prominent timer. |

## Design guarantees
- **Works with no internet / no API key.** Groq only adds wording polish; cleaning,
  decisions, charts, memo, chat, and the deck all render via fallbacks.
- **Never sends raw rows to the LLM** — only schemas, unique messy values, or
  computed aggregates.
- **Decisions are transparent heuristics** (see named constants at the top of
  `insights.py`) — no black-box ML.
- **Zero-dollar stack**: Python, Streamlit, pandas, plotly, rapidfuzz, free-tier Groq.
