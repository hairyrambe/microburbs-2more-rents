"""Settings and the ONE place to fix column names if the real files differ from my guesses.

Run `python src/build_model.py --inspect` to see the columns it found and how each was mapped.
If a mapping is wrong, put the real column name in OVERRIDES below.
"""
from pathlib import Path

import os

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / os.environ.get("MB_DATA", "data")   # put the supplied CSVs + rent_adverts.csv in data/ (git-ignored)
OUT = ROOT / "outputs"
FIGS = OUT / "figs"

TEAM = "2more"
AS_AT = "2026-07-31"          # task date: NOTHING after this may be used
VAL_START = "2026-05-01"      # our own validation: train before, check on May-Jul 2026

FILE_INPUT = DATA / "rents-input-flats-city-of-sydney.csv"
FILE_PAST_LEASES = DATA / "rents-past-leases-city-of-sydney.csv"
FILE_API_ADVERTS = DATA / "rent_adverts.csv"       # from src/pull_rents.py
FILE_BLOCKS = DATA / "blocks-homes-and-people-2021-2026.csv"
FILE_OUT = ROOT / f"rents_{TEAM}.csv"

# Standard name -> list of candidate raw column names (matched case-insensitively, on the
# part after the last '.', so 'attributes.bedrooms' matches 'bedrooms').
CANDIDATES = {
    "rent":   ["weekly_rent", "rent", "rent_pw", "price", "weekly_price", "advertised_rent", "rent_per_week"],
    "date":   ["listing_date", "listed_date", "list_date", "advert_date", "date", "first_listed", "listed", "listed_at"],
    "beds":   ["bedrooms", "beds"],
    "baths":  ["bathrooms", "baths"],
    "car":    ["car_spaces", "carspaces", "parking", "garages", "car_space", "cars"],
    "lat":    ["latitude", "lat"],
    "lon":    ["longitude", "lon", "lng"],
    "gnaf":   ["gnaf_id", "gnaf", "gnaf_pid"],
    "suburb": ["suburb", "area_name", "_suburb_queried", "locality"],
    "ptype":  ["property_type", "dwelling_type", "type"],
}

# Force a mapping here if auto-detection picks the wrong column, e.g. {"rent": "price_pw"}.
OVERRIDES = {}
