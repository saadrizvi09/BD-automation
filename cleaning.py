"""
cleaning.py — deterministic, demo-safe cleaning of raw bookings/partners/leads.

clean_bookings(df) -> (clean_df, log)   is the main entry; clean_partners /
clean_leads reuse the same normalizers. Cleaning is driven by HARDCODED maps
(primary) with a rapidfuzz fallback for unseen variants, so it is deterministic
and never depends on the network. The cleaning log proves real work was done.
"""

import re

import numpy as np
import pandas as pd

try:
    from rapidfuzz import process, fuzz
    _HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover - fallback if rapidfuzz missing
    _HAS_RAPIDFUZZ = False


# ----------------------------------------------------------------------------
# Canonical reference values + hardcoded variant maps
# ----------------------------------------------------------------------------
CANONICAL_CITIES = [
    "Delhi NCR", "Mumbai", "Bengaluru", "Hyderabad", "Pune", "Chennai",
    "Kolkata", "Ahmedabad", "Jaipur", "Chandigarh", "Dubai", "Singapore",
]

CITY_MAP = {
    "delhi ncr": "Delhi NCR", "gurgaon": "Delhi NCR", "ggn": "Delhi NCR",
    "new delhi": "Delhi NCR", "delhi": "Delhi NCR", "gurugram": "Delhi NCR",
    "noida": "Delhi NCR",
    "mumbai": "Mumbai", "bombay": "Mumbai",
    "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "blr": "Bengaluru",
    "hyderabad": "Hyderabad", "hyd": "Hyderabad",
    "pune": "Pune", "chennai": "Chennai", "madras": "Chennai",
    "kolkata": "Kolkata", "calcutta": "Kolkata",
    "ahmedabad": "Ahmedabad", "jaipur": "Jaipur", "chandigarh": "Chandigarh",
    "dubai": "Dubai", "singapore": "Singapore",
}

CANONICAL_CATEGORIES = [
    "Salon for Women", "Salon for Men", "Spa & Massage", "Home Deep Cleaning",
    "Bathroom & Kitchen Cleaning", "Sofa & Carpet Cleaning", "AC Service & Repair",
    "Appliance Repair", "Plumbing", "Electrician", "Carpenter", "Pest Control",
    "Painting", "RO / Water Purifier",
]

CATEGORY_MAP = {
    "salon for women": "Salon for Women", "salon - women": "Salon for Women",
    "salon women": "Salon for Women",
    "salon for men": "Salon for Men", "salon - men": "Salon for Men",
    "salon men": "Salon for Men",
    "spa & massage": "Spa & Massage", "spa and massage": "Spa & Massage",
    "spa": "Spa & Massage",
    "home deep cleaning": "Home Deep Cleaning", "deep cleaning": "Home Deep Cleaning",
    "bathroom & kitchen cleaning": "Bathroom & Kitchen Cleaning",
    "sofa & carpet cleaning": "Sofa & Carpet Cleaning",
    "ac service & repair": "AC Service & Repair", "ac repair": "AC Service & Repair",
    "a.c. service": "AC Service & Repair", "ac servicing": "AC Service & Repair",
    "ac service": "AC Service & Repair",
    "appliance repair": "Appliance Repair",
    "plumbing": "Plumbing", "electrician": "Electrician", "carpenter": "Carpenter",
    "pest control": "Pest Control", "painting": "Painting",
    "ro / water purifier": "RO / Water Purifier", "ro water purifier": "RO / Water Purifier",
    "water purifier": "RO / Water Purifier",
}

STATUS_MAP = {
    "completed": "completed", "complete": "completed", "done": "completed",
    "cancelled": "cancelled", "canceled": "cancelled", "cancel": "cancelled",
    "rescheduled": "rescheduled", "reschedule": "rescheduled", "resched": "rescheduled",
}


def _norm_key(s):
    """Lowercase, collapse whitespace, strip punctuation noise for map lookup."""
    s = str(s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _fuzzy(value_key, canonical_list, threshold=82):
    if not _HAS_RAPIDFUZZ or not value_key:
        return None
    match = process.extractOne(
        value_key, canonical_list, scorer=fuzz.WRatio
    )
    if match and match[1] >= threshold:
        return match[0]
    return None


def _standardize_column(series, hardcoded_map, canonical_list):
    """Return (clean_series, n_changed). Hardcoded map first, fuzzy fallback."""
    canon_lower = {c.lower(): c for c in canonical_list}
    changed = 0
    out = []
    for raw in series:
        if raw is None or (isinstance(raw, float) and np.isnan(raw)) or str(raw).strip() == "":
            out.append(np.nan)
            continue
        key = _norm_key(raw)
        canon = hardcoded_map.get(key)
        if canon is None:
            canon = canon_lower.get(key)
        if canon is None:
            canon = _fuzzy(key, canonical_list)
        if canon is None:
            canon = str(raw).strip()  # leave as-is, best effort
        if canon != str(raw):
            changed += 1
        out.append(canon)
    return pd.Series(out, index=series.index), changed


def parse_dates(series):
    """Parse mixed date formats robustly by trying each known format in turn.

    A single `dayfirst` flag can't serve both ISO (YYYY-MM-DD) and DD/MM/YYYY in
    one column — dayfirst=True wrongly flips ISO dates. So we parse the
    unambiguous formats explicitly, in order, and coalesce.
    """
    s = series.astype(str).str.strip()
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%y", "%d-%m-%Y", "%Y/%m/%d"):
        mask = result.isna()
        if not mask.any():
            break
        attempt = pd.to_datetime(s[mask], format=fmt, errors="coerce")
        result[mask] = attempt
    # final catch-all for anything still unparsed
    mask = result.isna()
    if mask.any():
        result[mask] = pd.to_datetime(s[mask], errors="coerce", dayfirst=True)
    return result, int(result.isna().sum())


# kept for back-compat with earlier internal name
_parse_dates = parse_dates


# ----------------------------------------------------------------------------
# Public cleaners
# ----------------------------------------------------------------------------
def clean_bookings(df):
    log = {}
    df = df.copy()
    log["rows_in"] = len(df)

    # strip whitespace on object columns
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].astype(str).str.strip().replace({"nan": np.nan, "": np.nan})

    # dedupe booking_id
    before = len(df)
    df = df.drop_duplicates(subset="booking_id", keep="first")
    log["duplicates_removed"] = before - len(df)

    # city
    df["city"], log["cities_standardized"] = _standardize_column(
        df["city"], CITY_MAP, CANONICAL_CITIES
    )
    # category
    df["service_category"], log["categories_standardized"] = _standardize_column(
        df["service_category"], CATEGORY_MAP, CANONICAL_CATEGORIES
    )
    # status
    df["status"], _ = _standardize_column(df["status"], STATUS_MAP, list(set(STATUS_MAP.values())))

    # dates
    df["date"], log["dates_unparsed"] = _parse_dates(df["date"])

    # numeric value: coerce, fix invalid (<=0) -> NaN then drop
    df["booking_value_inr"] = pd.to_numeric(df["booking_value_inr"], errors="coerce")
    invalid = (df["booking_value_inr"] <= 0) | df["booking_value_inr"].isna()
    log["invalid_values_fixed"] = int(invalid.sum())
    df = df[~invalid]

    df["commission_pct"] = pd.to_numeric(df["commission_pct"], errors="coerce").fillna(18.0)
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")

    # blanks in city/category after standardization
    log["blank_city_or_category"] = int(df["city"].isna().sum() + df["service_category"].isna().sum())
    df = df.dropna(subset=["city", "service_category", "date"])

    log["rows_out"] = len(df)
    df = df.reset_index(drop=True)
    return df, log


def clean_partners(df):
    df = df.copy()
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].astype(str).str.strip().replace({"nan": np.nan, "": np.nan})
    df = df.drop_duplicates(subset="partner_id", keep="first")
    df["city"], _ = _standardize_column(df["city"], CITY_MAP, CANONICAL_CITIES)
    df["primary_category"], _ = _standardize_column(
        df["primary_category"], CATEGORY_MAP, CANONICAL_CATEGORIES
    )
    df["status"] = df["status"].astype(str).str.strip().str.lower()
    df["onboard_date"], _ = parse_dates(df["onboard_date"])
    df["jobs_completed"] = pd.to_numeric(df["jobs_completed"], errors="coerce").fillna(0).astype(int)
    df["avg_rating"] = pd.to_numeric(df["avg_rating"], errors="coerce")
    return df.reset_index(drop=True)


def clean_leads(df):
    df = df.copy()
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].astype(str).str.strip().replace({"nan": np.nan, "": np.nan})
    df = df.drop_duplicates(subset="lead_id", keep="first")
    df["city"], _ = _standardize_column(df["city"], CITY_MAP, CANONICAL_CITIES)
    df["category_interest"], _ = _standardize_column(
        df["category_interest"], CATEGORY_MAP, CANONICAL_CATEGORIES
    )
    df["stage"] = df["stage"].astype(str).str.strip().str.lower().replace({"nan": np.nan})
    df["stage"] = df["stage"].fillna("new")
    df["created_date"], _ = parse_dates(df["created_date"])
    return df.reset_index(drop=True)


# Back-compat single-entry the spec names: clean(df) -> (clean_df, log)
def clean(df):
    return clean_bookings(df)
