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

## Ask your own sheet (works on ANY data, not just the BD template)
Upload — or connect a Google Sheet containing — a table that *doesn't* match the
bookings template (a pilot tracker, a CRM export, anything). The app keeps it as a
**custom table** and shows a **🔎 Ask your own sheet** panel: ask in plain English and
get a number **and** a chart back.
- *"total pipeline value by region"*, *"pie chart of spend by status"*,
  *"average score by owner"*, *"count of rows by stage"*, *"highest deal value by city"*.
- It auto-detects numeric vs categorical columns (even when a Sheet sends numbers as
  text), so it works on columns it has never seen.
- **Privacy holds:** the LLM sees only the **column names** (and a few category labels),
  never your rows — it returns a structured intent and *our pandas code* runs the maths.
  It also works with the **LLM switched off** (a keyword parser reads the real columns).
- By design the AI does **not** write or execute arbitrary code on your data — same
  "ask anything" flexibility, none of the security risk.

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

## Privacy & service accounts (what to tell a company)

The Google connection uses a **service account** — a robot Google identity with its
own email (e.g. `bd-report-bot@your-project.iam.gserviceaccount.com`), **not** your
personal Gmail. You can't (and shouldn't) log the app in as yourself; instead you
**share your sheet with the robot's email**, exactly like sharing with a colleague.

**Setup (one service account covers everything — read raw tabs + write the report back):**

| Step | Do this | Where |
|---|---|---|
| 1 | Create a free project | [console.cloud.google.com](https://console.cloud.google.com/) |
| 2 | Enable the **Google Sheets API** | APIs & Services → Library |
| 3 | Create a **Service Account** | IAM & Admin → Service Accounts |
| 4 | On it → **Keys → Add key → JSON** → download `key.json` | Service Account → Keys |
| 5 | Open your sheet → **Share** → paste the account's `client_email` as **Editor** | your Google Sheet |
| 6 | Upload `key.json` + paste the sheet URL in the app's **🔗 Connect a Google Sheet** panel | the app |

The app shows the exact email to share with once you upload the key.

**Why this is privacy-safe (lead with this in the interview):**
- **Least privilege** — the bot can *only* see sheets you explicitly share with it.
  Not your Drive, not your email. Un-share to revoke access instantly. No personal login.
- **Raw data never leaves your control** — cleaning, the decision engine (₹-at-risk,
  recruitment list, anomalies) and all charts are **100% local pandas**.
- **The LLM never sees a raw row** — Groq gets only computed aggregates + column
  schemas to polish wording, and the whole app runs **fully with the LLM switched off**.
- **Self-hostable, zero-dollar** — runs on the company's own laptop/server; the Sheets
  link is optional, with file upload and sample data as offline fallbacks.

One-liner: *"Our data stays in our own sheet; the app gets a read-by-invitation robot
key, does all the analysis locally, and the AI only ever sees anonymized totals — and
it works even with the AI off."*

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
