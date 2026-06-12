"""
data_generator.py — generate realistic, deliberately-messy sample data.

Run once:  python data_generator.py
Outputs into ./data/:
  - sample_bookings.xlsx   (~8,000 rows, last 12 weeks)
  - sample_partners.xlsx   (partner onboarding funnel)
  - sample_leads.xlsx      (partner-acquisition CRM export)

The mess (city/category spelling variants, dupes, blanks, bad values, mixed
date formats) is intentional — it's what makes the cleaning step visibly
valuable in the demo.
"""

import os
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

RNG_SEED = 42
random.seed(RNG_SEED)
np.random.seed(RNG_SEED)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

N_BOOKINGS = 8000
N_WEEKS = 12
TODAY = datetime(2026, 6, 12)            # matches the demo "current date"
START = TODAY - timedelta(weeks=N_WEEKS)

# ----------------------------------------------------------------------------
# Reference dimensions
# ----------------------------------------------------------------------------
CITY_WEIGHTS = {
    "Delhi NCR": 20, "Mumbai": 18, "Bengaluru": 16, "Hyderabad": 10,
    "Pune": 9, "Chennai": 8, "Kolkata": 6, "Ahmedabad": 5,
    "Jaipur": 4, "Chandigarh": 2, "Dubai": 1.5, "Singapore": 0.5,
}

# category -> (min_inr, max_inr, frequency_weight, commission_pct)
CATEGORIES = {
    "Salon for Women":              (800, 2500, 18, 0.20),
    "Salon for Men":                (300, 800, 16, 0.20),
    "Spa & Massage":                (1200, 3000, 8, 0.22),
    "Home Deep Cleaning":           (1500, 4000, 14, 0.18),
    "Bathroom & Kitchen Cleaning":  (500, 1500, 13, 0.18),
    "Sofa & Carpet Cleaning":       (600, 2000, 7, 0.18),
    "AC Service & Repair":          (500, 1800, 14, 0.17),
    "Appliance Repair":             (400, 1500, 8, 0.17),
    "Plumbing":                     (250, 1200, 7, 0.16),
    "Electrician":                  (250, 1000, 7, 0.16),
    "Carpenter":                    (300, 1500, 3, 0.16),
    "Pest Control":                 (1000, 3500, 3, 0.22),
    "Painting":                     (3000, 15000, 2, 0.15),
    "RO / Water Purifier":          (400, 1200, 3, 0.18),
}

SUB_SERVICES = {
    "Salon for Women": ["Haircut", "Facial", "Waxing", "Manicure", "Hair Spa"],
    "Salon for Men": ["Haircut", "Beard Styling", "Head Massage", "Hair Color"],
    "Spa & Massage": ["Swedish", "Deep Tissue", "Aromatherapy"],
    "Home Deep Cleaning": ["Full Home", "1BHK", "2BHK", "3BHK"],
    "Bathroom & Kitchen Cleaning": ["Bathroom", "Kitchen", "Combo"],
    "Sofa & Carpet Cleaning": ["Sofa", "Carpet", "Mattress"],
    "AC Service & Repair": ["Servicing", "Gas Refill", "Installation", "Repair"],
    "Appliance Repair": ["Washing Machine", "Refrigerator", "Microwave"],
    "Plumbing": ["Tap Repair", "Leakage", "Installation"],
    "Electrician": ["Switchboard", "Fan", "Wiring", "Light"],
    "Carpenter": ["Furniture Repair", "Door", "Assembly"],
    "Pest Control": ["General", "Termite", "Cockroach"],
    "Painting": ["Full Home", "1 Room", "Touch-up"],
    "RO / Water Purifier": ["Service", "Filter Change", "Installation"],
}

LEAD_SOURCES = ["app", "web", "referral", "ads"]

FIRST_NAMES = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Rohan",
               "Pooja", "Suresh", "Kavya", "Arjun", "Neha", "Deepak", "Divya",
               "Manish", "Ritu", "Sanjay", "Meena", "Karan", "Shreya"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Reddy", "Nair", "Iyer", "Gupta",
              "Singh", "Das", "Kumar", "Mehta", "Joshi", "Rao", "Khan", "Bose"]

# Messy spelling variants -> emitted in the raw data, cleaned back to canonical.
CITY_VARIANTS = {
    "Delhi NCR": ["Delhi NCR", "Gurgaon", "gurgaon ", "GGN", "New Delhi", "Delhi", "delhi ncr"],
    "Mumbai":    ["Mumbai", "Bombay", "mumbai ", "MUMBAI"],
    "Bengaluru": ["Bengaluru", "Bangalore", "blr", "BLR", "bengaluru "],
    "Hyderabad": ["Hyderabad", "Hyd", "hyderabad", "HYD"],
}

CATEGORY_VARIANTS = {
    "AC Service & Repair": ["AC Service & Repair", "AC Repair", "a.c. service",
                            "AC Servicing", "ac service & repair"],
    "Salon for Women":     ["Salon for Women", "Salon - Women", "salon for women",
                            "SALON FOR WOMEN"],
    "Salon for Men":       ["Salon for Men", "Salon - Men", "salon for men"],
    "Home Deep Cleaning":  ["Home Deep Cleaning", "home deep cleaning", "Deep Cleaning"],
}

# ----------------------------------------------------------------------------
# DELIBERATELY PLANTED SIGNALS — these drive the Action Center (the demo's point)
# ----------------------------------------------------------------------------
# Hot cells: high & growing demand + elevated cancellations + only ~2 active
# partners => flagged UNDERSUPPLIED with real ₹/week at risk and "recruit N".
HOT_CELLS = [
    ("Pune", "AC Service & Repair"),
    ("Hyderabad", "AC Service & Repair"),
    ("Bengaluru", "Home Deep Cleaning"),
    ("Mumbai", "Salon for Women"),
    ("Delhi NCR", "Spa & Massage"),
    ("Mumbai", "Home Deep Cleaning"),
    ("Delhi NCR", "AC Service & Repair"),
    ("Bengaluru", "Pest Control"),
    ("Hyderabad", "Painting"),
]
HOT_ACTIVE_PARTNERS = 2          # force few active partners in each hot cell
DECLINING_CITY = "Chennai"       # thinned last-week volume => revenue-drop alert


def _weighted_choice(weight_map):
    keys = list(weight_map.keys())
    weights = np.array([weight_map[k] for k in keys], dtype=float)
    weights /= weights.sum()
    return np.random.choice(keys, p=weights)


def _messy_city(canonical):
    variants = CITY_VARIANTS.get(canonical)
    if variants and random.random() < 0.45:
        return random.choice(variants)
    return canonical


def _messy_category(canonical):
    variants = CATEGORY_VARIANTS.get(canonical)
    if variants and random.random() < 0.40:
        return random.choice(variants)
    # random capitalization mess for the rest
    if random.random() < 0.10:
        return canonical.lower()
    return canonical


def _messy_name(name):
    r = random.random()
    if r < 0.15:
        return "  " + name + " "
    if r < 0.25:
        return name.upper()
    if r < 0.32:
        return name.lower()
    return name


def _format_date_messy(dt):
    """Emit mixed date formats so the parser has real work to do."""
    fmt = random.choice([
        "%Y-%m-%d", "%d/%m/%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y",
    ])
    return dt.strftime(fmt)


# ----------------------------------------------------------------------------
# Bookings
# ----------------------------------------------------------------------------
def _make_booking_row(i, canon_city, canon_cat, dt, cancel_p=0.08, pid=None):
    lo, hi, _w, comm = CATEGORIES[canon_cat]
    value = round(np.random.uniform(lo, hi), 0)
    status = np.random.choice(
        ["completed", "cancelled", "rescheduled"],
        p=[1 - cancel_p - 0.07, cancel_p, 0.07],
    )
    rating = float(np.random.choice([1, 2, 3, 4, 5], p=[0.02, 0.05, 0.13, 0.35, 0.45]))
    if random.random() < 0.05:
        rating = np.nan
    if pid is None:
        pid = f"P{random.randint(1, 232):04d}"
    pname = _messy_name(f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}")
    return {
        "booking_id": f"BKG{100000 + i}",
        "date": _format_date_messy(dt),
        "city": _messy_city(canon_city),
        "service_category": _messy_category(canon_cat),
        "sub_service": random.choice(SUB_SERVICES[canon_cat]),
        "partner_id": pid,
        "partner_name": pname,
        "booking_value_inr": value,
        "commission_pct": round(comm * 100, 1),
        "status": random.choice([status, status.upper(), status.capitalize()]),
        "rating": rating,
        "lead_source": random.choice(LEAD_SOURCES),
        "customer_type": np.random.choice(["new", "repeat"], p=[0.35, 0.65]),
    }


def generate_bookings():
    cat_list = list(CATEGORIES.keys())
    cat_weights = np.array([CATEGORIES[c][2] for c in cat_list], dtype=float)
    cat_weights /= cat_weights.sum()

    rows = []
    i = 0
    # ---- base demand: roughly uniform across the 12 weeks so WoW baselines are
    #      stable (planted signals below create the deliberate movement) ----
    for _ in range(N_BOOKINGS):
        canon_city = _weighted_choice(CITY_WEIGHTS)
        canon_cat = np.random.choice(cat_list, p=cat_weights)
        day_offset = random.randint(0, N_WEEKS * 7 - 1)
        dt = START + timedelta(days=day_offset)
        rows.append(_make_booking_row(i, canon_city, canon_cat, dt))
        i += 1

    # ---- PLANTED hot cells: heavy, growing demand + high cancellations in the
    #      last 2 weeks, canonical spellings so the signal reliably survives ----
    for (city, cat) in HOT_CELLS:
        # prior week (8-14 days ago): moderate volume, moderate cancellations
        for _ in range(70):
            dt = TODAY - timedelta(days=random.randint(8, 14))
            rows.append(_make_booking_row(i, city, cat, dt, cancel_p=0.09))
            i += 1
        # last week (0-7 days ago): higher volume + cancellation SPIKE (no availability)
        for _ in range(95):
            dt = TODAY - timedelta(days=random.randint(0, 7))
            rows.append(_make_booking_row(i, city, cat, dt, cancel_p=0.25))
            i += 1

    df = pd.DataFrame(rows)

    # ---- PLANTED decline: thin the declining city's last-7-day volume so its
    #      recent revenue drops sharply vs the prior week => red alert ----
    from cleaning import parse_dates
    df["_d"], _ = parse_dates(df["date"])
    last_wk = df["_d"] >= (TODAY - timedelta(days=7))
    decl = df[last_wk & (df["city"].apply(lambda c: _norm_match(c, DECLINING_CITY)))]
    drop_idx = decl.sample(frac=0.65, random_state=11).index
    df = df.drop(index=drop_idx).drop(columns="_d").reset_index(drop=True)

    # ---- inject structural mess ----
    dup = df.sample(frac=0.03, random_state=1).copy()
    df = pd.concat([df, dup], ignore_index=True)

    blank_idx = df.sample(frac=0.02, random_state=2).index
    half = len(blank_idx) // 2
    df.loc[blank_idx[:half], "city"] = ""
    df.loc[blank_idx[half:], "service_category"] = ""

    bad_idx = df.sample(frac=0.01, random_state=3).index
    df.loc[bad_idx, "booking_value_inr"] = np.random.choice([0, -100, -500], size=len(bad_idx))

    df = df.sample(frac=1.0, random_state=7).reset_index(drop=True)
    return df


def _norm_match(raw, canonical):
    """True if a (possibly messy) city string maps to the canonical city."""
    variants = {v.strip().lower() for v in CITY_VARIANTS.get(canonical, [canonical])}
    variants.add(canonical.lower())
    return str(raw).strip().lower() in variants


# ----------------------------------------------------------------------------
# Partners
# ----------------------------------------------------------------------------
def generate_partners():
    rows = []
    pid_num = 1
    cat_pool = list(CATEGORIES.keys())
    for city, w in CITY_WEIGHTS.items():
        cohort = max(8, int(w * 2.2))
        for _ in range(cohort):
            if pid_num > 232:
                break
            cat = _weighted_choice({c: CATEGORIES[c][2] for c in CATEGORIES})
            onboard = START - timedelta(days=random.randint(0, 240))
            status = np.random.choice(
                ["applied", "onboarded", "active", "churned"],
                p=[0.18, 0.17, 0.55, 0.10],
            )
            jobs = 0 if status in ("applied", "onboarded") else random.randint(5, 220)
            rating = round(np.random.uniform(3.6, 4.9), 1) if jobs else np.nan
            rows.append({
                "partner_id": f"P{pid_num:04d}",
                "_city": city, "_cat": cat, "_status": status,
                "name": _messy_name(f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"),
                "onboard_date": _format_date_messy(onboard),
                "jobs_completed": jobs,
                "avg_rating": rating,
                "lead_source": random.choice(["referral", "ad", "walk-in", "agency"]),
            })
            pid_num += 1

    df = pd.DataFrame(rows)

    # ---- force each hot cell to have exactly HOT_ACTIVE_PARTNERS active (so the
    #      gap engine sees real undersupply). Demote extras to 'churned'. ----
    for (city, cat) in HOT_CELLS:
        in_cell = df[(df["_city"] == city) & (df["_cat"] == cat)].index
        df.loc[in_cell, "_status"] = "churned"
        keep = list(in_cell[:HOT_ACTIVE_PARTNERS])
        # if too few partners exist for this cell, mint new ones
        need = HOT_ACTIVE_PARTNERS - len(keep)
        for _ in range(need):
            pid_num += 1
            new = {
                "partner_id": f"P{pid_num:04d}", "_city": city, "_cat": cat,
                "_status": "active",
                "name": _messy_name(f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"),
                "onboard_date": _format_date_messy(START - timedelta(days=random.randint(0, 240))),
                "jobs_completed": random.randint(40, 120),
                "avg_rating": round(np.random.uniform(3.6, 4.9), 1),
                "lead_source": random.choice(["referral", "ad", "walk-in", "agency"]),
            }
            df = pd.concat([df, pd.DataFrame([new])], ignore_index=True)
        if keep:
            df.loc[keep, "_status"] = "active"
            df.loc[keep, "jobs_completed"] = df.loc[keep, "jobs_completed"].clip(lower=40)

    # finalize: apply messy spellings, drop helper cols
    df["city"] = df["_city"].apply(_messy_city)
    df["primary_category"] = df["_cat"].apply(_messy_category)
    df["status"] = df["_status"].apply(lambda s: random.choice([s, s.capitalize()]))
    df = df.drop(columns=["_city", "_cat", "_status"])
    df = df[["partner_id", "name", "city", "primary_category", "onboard_date",
             "status", "jobs_completed", "avg_rating", "lead_source"]]
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------
# Leads (acquisition CRM)
# ----------------------------------------------------------------------------
def generate_leads():
    rows = []
    owners = ["Aarti", "Vivek", "Sunil", "Tara", "Imran"]
    for i in range(1500):
        canon_city = _weighted_choice(CITY_WEIGHTS)
        cat = _weighted_choice({c: CATEGORIES[c][2] for c in CATEGORIES})
        created = START + timedelta(days=random.randint(0, N_WEEKS * 7 - 1))
        stage = np.random.choice(
            ["new", "contacted", "qualified", "onboarded", "lost"],
            p=[0.28, 0.25, 0.18, 0.17, 0.12],
        )
        stage_val = stage
        if random.random() < 0.03:
            stage_val = ""  # light mess: a few blank stages
        rows.append({
            "lead_id": f"LD{5000 + i}",
            "partner_name": _messy_name(f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"),
            "city": _messy_city(canon_city),
            "category_interest": _messy_category(cat),
            "source": random.choice(["referral", "ad", "walk-in", "agency"]),
            "stage": stage_val,
            "created_date": _format_date_messy(created),
            "owner": random.choice(owners),
        })
    return pd.DataFrame(rows)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print("Generating bookings...")
    bookings = generate_bookings()
    print("Generating partners...")
    partners = generate_partners()
    print("Generating leads...")
    leads = generate_leads()

    bookings.to_excel(os.path.join(DATA_DIR, "sample_bookings.xlsx"), index=False)
    partners.to_excel(os.path.join(DATA_DIR, "sample_partners.xlsx"), index=False)
    leads.to_excel(os.path.join(DATA_DIR, "sample_leads.xlsx"), index=False)

    print(f"Done. bookings={len(bookings)}  partners={len(partners)}  leads={len(leads)}")
    print(f"Written to: {DATA_DIR}")


if __name__ == "__main__":
    main()
