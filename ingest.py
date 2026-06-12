"""
ingest.py — multi-file upload, auto-detect by columns, auto-merge.

load_and_merge(files) accepts uploaded files in ANY order, detects each by its
columns (booking_id -> bookings, stage -> leads, onboard_date/primary_category
-> partners), cleans them, enriches bookings with partner status/city, and
returns (dict_of_dataframes, merge_log). This is the "pull 3 exports and
VLOOKUP" grind, automated — call out the merge log in the demo.
"""

import os

import pandas as pd

from cleaning import clean_bookings, clean_partners, clean_leads


def _read_any(file):
    """Read an uploaded file or path into a DataFrame (csv or xlsx)."""
    name = getattr(file, "name", str(file)).lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)


def _detect_kind(df):
    cols = set(c.lower() for c in df.columns)
    if "booking_id" in cols:
        return "bookings"
    if "lead_id" in cols or "stage" in cols:
        return "leads"
    if "onboard_date" in cols or "primary_category" in cols:
        return "partners"
    return "unknown"


def load_and_merge(files):
    """files: list of uploaded file objects or paths. Returns (data, merge_log)."""
    raw = {"bookings": None, "partners": None, "leads": None}
    detected = []

    for f in files:
        try:
            df = _read_any(f)
        except Exception as e:
            detected.append(f"skipped {getattr(f, 'name', f)} ({e})")
            continue
        kind = _detect_kind(df)
        if kind in raw and raw[kind] is None:
            raw[kind] = df
            detected.append(f"{getattr(f, 'name', 'file')} → {kind} ({len(df)} rows)")
        else:
            detected.append(f"{getattr(f, 'name', 'file')} → {kind} (ignored)")

    data, cleaning_logs = _clean_and_join(raw)
    merge_log = _build_log(data, detected, cleaning_logs)
    return data, merge_log


def load_samples(data_dir=None):
    """Load the three bundled sample files for the scripted demo."""
    data_dir = data_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    raw = {
        "bookings": pd.read_excel(os.path.join(data_dir, "sample_bookings.xlsx")),
        "partners": pd.read_excel(os.path.join(data_dir, "sample_partners.xlsx")),
        "leads": pd.read_excel(os.path.join(data_dir, "sample_leads.xlsx")),
    }
    data, cleaning_logs = _clean_and_join(raw)
    detected = [
        f"sample_bookings.xlsx → bookings ({len(raw['bookings'])} rows)",
        f"sample_partners.xlsx → partners ({len(raw['partners'])} rows)",
        f"sample_leads.xlsx → leads ({len(raw['leads'])} rows)",
    ]
    merge_log = _build_log(data, detected, cleaning_logs)
    return data, merge_log


def _clean_and_join(raw):
    data = {}
    cleaning_logs = {}

    if raw.get("bookings") is not None:
        bookings, blog = clean_bookings(raw["bookings"])
        cleaning_logs["bookings"] = blog
    else:
        bookings = pd.DataFrame()

    partners = clean_partners(raw["partners"]) if raw.get("partners") is not None else pd.DataFrame()
    leads = clean_leads(raw["leads"]) if raw.get("leads") is not None else pd.DataFrame()

    # enrich bookings <- partners on partner_id
    enriched = 0
    if not bookings.empty and not partners.empty and "partner_id" in bookings.columns:
        pslim = partners[["partner_id", "status", "city"]].rename(
            columns={"status": "partner_status", "city": "partner_city"}
        )
        before = len(bookings)
        bookings = bookings.merge(pslim, on="partner_id", how="left")
        enriched = int(bookings["partner_status"].notna().sum())
        assert len(bookings) == before  # left join must not duplicate

    data["bookings"] = bookings
    data["partners"] = partners
    data["leads"] = leads
    data["_enriched"] = enriched
    return data, cleaning_logs


def _build_log(data, detected, cleaning_logs):
    nb = len(data.get("bookings", []))
    npart = len(data.get("partners", []))
    nl = len(data.get("leads", []))
    n_files = sum(1 for k in ("bookings", "partners", "leads") if len(data.get(k, [])) > 0)
    enriched = data.get("_enriched", 0)

    summary = (
        f"Merged {n_files} file(s) — {nb:,} bookings"
        + (f" enriched with {npart} partner records" if npart else "")
        + (f", {nl:,} acquisition leads loaded" if nl else "")
        + "."
    )
    return {
        "summary": summary,
        "detected": detected,
        "bookings_enriched": enriched,
        "cleaning": cleaning_logs,
        "counts": {"bookings": nb, "partners": npart, "leads": nl},
    }
