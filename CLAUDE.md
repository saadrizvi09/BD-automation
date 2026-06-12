# CLAUDE.md — BD Report Automation (Interview Demo)

## What this is
A Streamlit app that replaces the repetitive 80% of a marketplace BD/ops analyst's week (think
Urban Company). It ingests *multiple* raw exports, auto-merges and cleans them, finds what's broken,
outputs **recommended actions with a rupee impact**, draws the charts as evidence, **answers ad-hoc
questions in plain English**, and **exports the finished leadership deck in one click** — in seconds.

The full loop: ingest many files → merge → clean → decide (with ₹ impact) → chat → deliver the deck.

## The big idea (this is what makes it land)
The product is **decisions, not dashboards.** Every company already has dashboards; "I made charts
faster" is not impressive. What IS impressive: the tool tells you *what's broken and what to do
about it, with money attached.* "₹4.2L/week is leaking from undersupply in these 5 city-category
cells — recruit here" beats any pie chart. Charts are the evidence; the decision is the product.
Lead the demo with the Action Center (problems + actions + ₹), then scroll to charts.

## Who it's for (READ THIS — it drives every decision)
This is a demo for a **Business Development role interview**, NOT an engineering interview.
The interviewer will judge:
1. **Whether a real business problem is solved** — does it surface what's broken and what to do?
   The recruitment action list + ₹ impact + alerts are the headline. This matters most.
2. **Realism of the output** — charts and numbers must look like a real analyst's polished work
   (₹ formatting, % labels, sorted bars, proper titles). Toy charts fail.
3. **Speed** — "this takes an analyst ~3 hours, watch it happen in 5 seconds." Show the elapsed
   generation time prominently on screen.

Nobody will read the code. Optimize for a flawless, fast, realistic live demo. Do NOT over-engineer.

## Hard constraints
- **Everything free.** Python, Streamlit, pandas, plotly, rapidfuzz, groq free tier. No paid services.
- **The demo must NOT break on conference wifi.** Everything renders fully **without** the LLM.
  Groq only adds polish — the cleaning of ambiguous values, the memo wording, and chat phrasing.
  Every LLM call has a fallback (hardcoded maps, a templated memo, keyword-parsed chat answers), so
  if Groq is missing/rate-limited/offline, the app keeps working end-to-end.
- **Never send the full dataset to the LLM.** Free-tier Groq is ~12K tokens/min, 100K/day on
  llama-3.3-70b-versatile. Send only column schemas, lists of unique messy values, or computed
  aggregates — never raw rows. Dumping data into the prompt = a 429 mid-demo.
- Single Streamlit app, runs locally with `streamlit run app.py`.

## Stack
- Python 3.11+
- streamlit (UI + multi-file upload + chat + download button)
- pandas, numpy (merge, cleaning, aggregation, simple forecast)
- plotly (charts — interactive, clean styling)
- kaleido (export plotly figures to PNG for the deck — REQUIRED for report export)
- python-pptx (generate the leadership .pptx deck); fpdf2 optional for a PDF alternative
- rapidfuzz (fuzzy matching for messy categorical values)
- groq (LLM: ambiguous cleaning, memo, NL query, chat) — OpenAI-compatible
- openpyxl (read/write xlsx)
All free. No paid services anywhere.

## File structure
```
CLAUDE.md            # this file
requirements.txt
data_generator.py    # generates the fake sample data (run once): bookings, partners, leads
ingest.py            # multi-file upload + auto-detect + auto-merge (+ merge log)
cleaning.py          # all cleaning logic + cleaning log
insights.py          # DECISION ENGINE: gap analysis, alerts, churn, forecast, ₹ impact
charts.py            # the chart builders
llm.py               # Groq integration + fallbacks (memo, clean, NL query, chat)
export.py            # build the leadership .pptx (and optional .pdf) deck
app.py               # Streamlit app (ties it together)
data/                # generated sample_bookings.xlsx, sample_partners.xlsx, sample_leads.xlsx
```

## Build order & priority (BUILD CORE FIRST, REHEARSE, THEN ADD STRETCH)
Everything is in this spec, but it is tiered on purpose. Get the CORE working end-to-end and
rehearse the demo *before* touching STRETCH. Each stretch item is one more thing that can break live.

**CORE (must work, this is the demo):**
1. `data_generator.py` → realistic messy sample data (bookings + partners + leads).
2. `cleaning.py` → clean df + cleaning log.
3. `insights.py` → gap analysis + anomalies + ₹ impact + KPIs. **The core value.**
4. `charts.py` → the chart figures (evidence).
5. `llm.py` → action memo + cleaning fallback (with graceful fallbacks).
6. `app.py` → Action Center on top, charts below, prominent timer, **Load sample data** button.

**STRETCH (add only once CORE works and is rehearsed):**
7. `ingest.py` → multi-file upload + auto-merge (the "pull 3 exports and VLOOKUP" story).
8. `export.py` → one-click leadership .pptx deck (the analyst's actual deliverable).
9. Chat box in `app.py` + `chat_answer` in `llm.py` → ad-hoc Q&A over the data.
10. `forecast()` + `suggested_targets()` in `insights.py` → next-week outlook.
11. `churn_risk()` panel → partners trending to churn.

---

## 1. Fake data spec (`data_generator.py`)
Generate **~8,000 booking rows** spanning the **last 12 weeks** (daily dates) so week-over-week
trends exist. Output `data/sample_bookings.xlsx`.

**Booking columns:**
`booking_id, date, city, service_category, sub_service, partner_id, partner_name,
booking_value_inr, commission_pct, status, rating, lead_source, customer_type`

**Cities** (weight volume so it's NOT uniform — metros dominate):
Delhi NCR (20), Mumbai (18), Bengaluru (16), Hyderabad (10), Pune (9), Chennai (8),
Kolkata (6), Ahmedabad (5), Jaipur (4), Chandigarh (2), Dubai (1.5), Singapore (0.5)

**Categories** with realistic ₹ ranges and frequency weights (beauty + cleaning are high-frequency):
| category | ₹ range | weight |
|---|---|---|
| Salon for Women | 800–2500 | high |
| Salon for Men | 300–800 | high |
| Spa & Massage | 1200–3000 | med |
| Home Deep Cleaning | 1500–4000 | high |
| Bathroom & Kitchen Cleaning | 500–1500 | high |
| Sofa & Carpet Cleaning | 600–2000 | med |
| AC Service & Repair | 500–1800 | high |
| Appliance Repair | 400–1500 | med |
| Plumbing | 250–1200 | med |
| Electrician | 250–1000 | med |
| Carpenter | 300–1500 | low |
| Pest Control | 1000–3500 | low |
| Painting | 3000–15000 | low (high value) |
| RO / Water Purifier | 400–1200 | low |

- `commission_pct`: 15–25% by category.
- `status`: completed (~85%), cancelled (~8%), rescheduled (~7%).
- `rating`: 1–5 skewed high (mostly 4–5), ~5% null.
- `lead_source`: app, web, referral, ads.
- `customer_type`: new (~35%), repeat (~65%).

**Inject deliberate MESS** (so the cleaning step is visibly valuable — this is core to the demo):
- City variants: "Gurgaon", "gurgaon ", "GGN", "Bangalore"/"blr", "Bombay", "New Delhi"/"Delhi", "Hyd".
- Category variants: "AC Repair"/"a.c. service"/"AC Servicing", "Salon - Women"/"salon for women",
  random capitalization.
- ~3% duplicate booking_ids.
- ~2% blank city or category.
- ~1% zero/negative booking_value.
- Mixed date formats (DD/MM/YYYY, YYYY-MM-DD, DD-Mon-YY).
- Leading/trailing whitespace and random caps in partner_name.

**Also generate `data/sample_partners.xlsx`** for the onboarding funnel:
`partner_id, name, city, primary_category, onboard_date, status, jobs_completed, avg_rating, lead_source`
- `status`: applied / onboarded / active / churned, with realistic drop-off
  (e.g. 100 applied → 60 onboarded → 45 active → 10 churned per cohort).

**Also generate `data/sample_leads.xlsx`** — a partner-acquisition CRM export (BD = bringing on supply):
`lead_id, partner_name, city, category_interest, source, stage, created_date, owner`
- ~1,500 leads. `source`: referral / ad / walk-in / agency. `stage`: new → contacted → qualified →
  onboarded → lost, with realistic funnel drop-off. Light mess (city variants, a few blank stages).
- Some onboarded leads correspond to partners (so the merge has something to join on).

### Multi-file ingest & auto-merge (`ingest.py`) — STRETCH
`load_and_merge(files) -> (dict_of_dataframes, merge_log)`:
- Accept multiple uploaded files in ANY order. **Auto-detect each by its columns**: `booking_id`
  present → bookings; `stage` present → leads; `onboard_date`/`primary_category` present → partners.
- Join bookings ← partners on `partner_id` to enrich bookings with partner status/city. Handle key
  mismatches and missing files gracefully (work with whatever subset was uploaded).
- Keep leads as the acquisition-funnel table.
- Return a **merge log**: e.g. "Merged 3 files — 8,000 bookings enriched with 420 partner records,
  1,500 acquisition leads loaded." This mirrors the analyst's "pull 3 exports and VLOOKUP" grind;
  call it out in the demo.

---

## 2. Cleaning (`cleaning.py`)
`clean(df) -> (clean_df, log)`. Steps:
- Strip whitespace, normalize case on text columns.
- Map city variants → canonical via a **hardcoded dict** (primary) + rapidfuzz fallback for unseen.
- Map category variants → canonical (hardcoded dict + rapidfuzz).
- Parse mixed date formats → datetime.
- Drop duplicate booking_ids (keep first).
- Null or drop invalid booking_value (<= 0).
- Normalize status values.
- Build a **cleaning log** dict: rows in, duplicates removed, city values standardized,
  category values standardized, invalid values fixed, blanks handled. Display this in the UI —
  it proves the tool did real work.

The hardcoded maps make cleaning deterministic and demo-safe. The LLM (below) is only for
genuinely ambiguous leftovers, and is optional.

---

## 3. Charts (`charts.py`) — 8 figures, each tied to a BD question
Use plotly. Clean palette, titles, ₹ formatting, % labels, sorted where ranked. Return figures.
1. **Pie** — revenue share by service category (the hero chart).
2. **Donut** — booking share by city.
3. **Ranked bar** — revenue by city (descending).
4. **Line** — week-over-week bookings & revenue trend.
5. **Funnel** (or bar) — partner onboarding funnel (applied→onboarded→active) from partners data.
6. **Bar** — demand-supply gap by city (bookings vs active partners). This is the "action" chart:
   highlights cities where supply is short → "recruit here."
7. **Stacked bar** — completed vs cancelled vs rescheduled by category (quality/ops).
8. **Bar** — top services by average order value (AOV).

Add a small KPI row at the top: total GMV (₹), total bookings, AOV, active partners, completion rate.

---

## 4. Decision engine (`insights.py`) — THE part that solves the real problem
This is the difference between "a dashboard" and "I solved your problem." All pure pandas, $0.
**Keep every threshold as a named constant at the top of the file, and make each rule explainable
in one sentence** — you must be able to answer "how does this work?" in the interview.

### `demand_supply_gap(bookings, partners)` — the centerpiece
For each city × category cell, compute:
- demand = bookings in the recent window + week-over-week demand growth
- supply = number of *active* partners in that cell
- utilization = bookings per active partner
- cancellation rate (proxy for demand lost to no availability)
- **gap flag**: UNDERSUPPLIED if demand is high AND utilization is high AND cancellation rate is
  elevated AND active partners are few; OVERSUPPLIED if utilization is very low.
- **recommended_partner_adds** = ceil(weekly_demand / target_jobs_per_partner_per_week) − current_active
- **est_revenue_at_risk_per_week** = unmet/cancelled demand × AOV × commission% (money on the table)

Return a table ranked worst-gap-first, plus the **total ₹/week at risk** across all cells.
This produces the headline line: *"Recruit ~35 partners for AC Service in Pune — demand +22% WoW,
18% cancellations from no availability, 12 active partners, ~₹3.1L/week at risk."*

### `anomalies(bookings)` — catch problems early
Week-over-week % change in revenue and bookings per city and per category (last week vs prior /
trailing average). Flag when beyond thresholds — e.g. revenue down >10%, cancellations up >50%,
avg rating drop >0.3. Return a list of `{entity, metric, change, severity}` → renders as red/amber
alerts. ("🔴 Mumbai bookings down 15% WoW", "🟠 Salon for Women cancellations up 2x").

### `churn_risk(partners, bookings)` — optional, only if time
Per active partner, look at jobs trend over the last 3 weeks, rating trend, and days idle.
Flag if jobs dropped >40% over 3 weeks AND (rating < 4 OR idle > N days). Return count + list
per city. Partner CAC is high, so "23 partners at churn risk in Delhi NCR" is real money.

### `kpi_summary(bookings, partners)`
total GMV (₹), total bookings, AOV, active partners, completion rate, and total ₹/week at risk.

### `forecast(bookings)` and `suggested_targets(...)` — STRETCH
Project next week's bookings/revenue per city (and overall) with a **simple, explainable** method:
trailing 4-week moving average, or a linear trend via `numpy.polyfit`. No heavy ML.
`suggested_targets` = forecast × a small growth factor (e.g. +5%), and flag cities tracking below
trend. Return projections + a one-line "next-week outlook." Charts: extend the trend line (#4) with
a dashed forecast segment. Keep it defensible — you must explain the method in one sentence.

---

## 5. Groq (`llm.py`) — with fallbacks
Model: `llama-3.3-70b-versatile`. Read key from `GROQ_API_KEY` env var. OpenAI-compatible client.

Four uses, **each with a fallback so the app works offline**:
- **action_memo(insights)** → send the computed gap table (top rows), the alerts, and the KPIs
  (NUMBERS ONLY, never raw data); get back a one-page memo: top 3 problems, top 3 opportunities,
  recommended actions, total ₹ impact. **Fallback: build the same memo from a template using the
  computed numbers** (no LLM). The memo must ALWAYS exist — it's the headline artifact.
- **clean_ambiguous(unique_values)** → send the list of unique messy category/city strings, ask for a
  canonical mapping as JSON. Fallback: the hardcoded dict in cleaning.py.
- **nl_query(question, schema)** → user asks in plain English ("revenue by city for beauty"); LLM
  returns `{chart_type, group_by, metric, filter}` JSON; app renders it with pandas+plotly.
  Send ONLY the schema (column names + 3 sample rows), never the data. Fallback: skip the query box.
- **summary(aggregates)** → optional short narrative on the charts. Fallback: pre-written string.
- **chat_answer(question, schema, df_helpers)** — STRETCH → conversational Q&A over the data
  ("what was Mumbai's AC revenue last week?"). The LLM returns a structured intent
  (metric + group_by + filter); YOUR code runs the pandas aggregation and returns the number +
  optional chart; the LLM then phrases the answer. Send ONLY schema + the computed result, never raw
  rows. Keep a short history in `st.session_state`. Fallback: keyword-parse the question (extract
  city/category/metric) and answer from pandas, so the box still works with no LLM. This replaces the
  analyst's constant Slack pings.

Wrap every call in try/except. On 429 or any error, silently use the fallback. The app must
never block on the LLM.

---

## 6. Streamlit app (`app.py`) — UX
Layout order on screen (top = headline, bottom = evidence):
- Title: "BD Performance & Action Report — Automated". Subtitle naming the time saved.
- Top controls:
  - **[Upload files]** — `st.file_uploader(accept_multiple_files=True)` for xlsx/csv. Drop bookings,
    partners, and leads together → `ingest.load_and_merge` → show the **merge log**. (STRETCH)
  - **[Load sample data]** — loads all three sample files. Use this for the scripted demo.
- On load: run cleaning, show the **cleaning log** (messy → clean stats) and a **timer**.
- **[Generate Report]** → render, in this order:
  1. **KPI row** — GMV, bookings, AOV, active partners, completion rate, **total ₹/week at risk**.
  2. **ACTION CENTER (the headline)** — action memo + ranked recruitment action list (city × category,
     partners to add, ₹ at risk) + red/amber anomaly alerts. Seen first, remembered.
  3. **[Download leadership deck]** button (`st.download_button`) right under the Action Center. (STRETCH)
  4. **Charts** below, in a grid, labeled "Supporting evidence."
  5. **Next-week outlook** panel (forecast + suggested targets). (STRETCH)
  6. **Churn-risk** panel. (STRETCH, optional)
- **Ask-anything chat box** (NL query/chat over the data, with history). (STRETCH)
- Display the elapsed generation time PROMINENTLY, e.g. "Report generated in 4.2s" — the punchline.
- Clean, professional styling — this is shown to business stakeholders.

---

## 7. Report export (`export.py`) — STRETCH, the analyst's actual deliverable
The analyst's job output is the leadership deck. Producing it in one click is the strongest proof
the grind is automated.
`build_pptx(kpis, memo, action_table, alerts, figures) -> bytes` using python-pptx:
- Title slide → KPI slide → Action Center slide (memo + recruitment table + alerts) → one slide per
  key chart.
- Convert each plotly figure to PNG via `fig.to_image(format="png")` (needs kaleido) and insert it.
- Serve the bytes through the `st.download_button` in the app.
- Optional `build_pdf(...)` via fpdf2 as an alternative format.
**Guardrail:** if chart-image export fails (kaleido issue), fall back to a text-only deck
(tables + memo) so the download button NEVER errors live.

---

## Run instructions
```
python -m venv venv && source venv/bin/activate   # (Windows: venv\Scripts\activate)
pip install -r requirements.txt
python data_generator.py        # creates data/ samples once
export GROQ_API_KEY=your_key     # (Windows: set GROQ_API_KEY=your_key) — optional; app works without it
streamlit run app.py
```

## Demo script (for the human, not code)
The CORE flow (steps 1–4) must carry the demo on its own. Add 0/5/6 only if those stretch
features are built and you've rehearsed them.

0. (If ingest built) "I drop in the three raw exports — bookings, partners, leads — and it merges
   them automatically. That's the VLOOKUP grind, gone." → show the merge log.
1. "Every Monday a BD analyst rebuilds this by hand — cleaning messy city/category names, pivoting,
   charting, then hunting for what's wrong. ~3 hours."
2. Click **Load sample data** → show the messy table + cleaning log ("47 duplicate bookings removed,
   6 city spellings standardized, 12 invalid values fixed").
3. Click **Generate Report** → point at the timer: "~4 seconds." Go straight to the **Action Center**:
   "It found ₹4.2L/week leaking from undersupply, and here's exactly where to recruit." Read one
   recruitment line and one alert aloud.
4. Scroll to the charts: "And here's the evidence behind every one of those calls."
5. (If export built) Click **Download leadership deck** → open the .pptx: "That's the Monday deck for
   leadership — done in one click."
6. (If chat built) Type a question: "Anyone can just ask it, like they'd ping the analyst."
Close with: "Zero-dollar stack — Python, Streamlit, a free LLM key. Runs on a laptop. And it can be
scheduled to email this every Monday with no one touching it."

## Guardrails (do not violate)
- **Build and rehearse CORE before STRETCH.** A polished CORE demo beats a feature-rich broken one.
- The product is decisions, not charts. The Action Center (actions + ₹ impact + alerts) is the
  headline; charts are evidence below it.
- All decision logic is **simple, transparent heuristics with named thresholds** — explainable in
  one sentence each. No black-box ML you can't defend in the interview.
- Charts render with pandas + plotly only. The LLM never draws a chart and never computes the numbers.
- Full data NEVER goes into an LLM prompt — schema / unique values / computed aggregates only.
- App works end-to-end with no internet / no API key (every LLM call has a fallback). The deck export
  falls back to text-only if chart images fail.
- One Streamlit app, runs locally (deployable free to Streamlit Community Cloud for a shareable URL).
  No separate backend, database, or React.