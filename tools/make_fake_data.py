"""FAKE data with the documented column names, only to test the pipeline before the real files arrive.
Writes to fake_data/ (git-ignored). Never submit anything built from this.

    python tools/make_fake_data.py && MB_DATA=fake_data python src/build_model.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(1)
out = Path(__file__).resolve().parent.parent / "fake_data"
out.mkdir(exist_ok=True)
subs = ["Surry Hills", "Glebe (NSW)", "Waterloo (NSW)", "Zetland", "Pyrmont", "Redfern", "Sydney", "Ultimo"]
base = dict(zip(subs, [720, 640, 650, 700, 760, 650, 820, 600]))

n_b = 900
bld = pd.DataFrame({"building_address": [f"{i} Fake St" for i in range(n_b)],
                    "suburb": rng.choice(subs, n_b),
                    "flats_in_building": rng.integers(4, 300, n_b),
                    "bq": rng.normal(0, 60, n_b)})
bld["lat"] = -33.89 + rng.normal(0, .01, n_b)
bld["lon"] = 151.20 + rng.normal(0, .01, n_b)
N = 8000
f = bld.sample(N, replace=True, random_state=1).reset_index(drop=True)
f["gnaf_id"] = [f"GANSW{700000000 + i}" for i in range(N)]
f["bedrooms"] = rng.choice([0, 1, 2, 3], N, p=[.1, .4, .4, .1])
f["bathrooms"] = np.clip(f["bedrooms"], 1, 2)
f["car_space"] = rng.choice([1, 0, np.nan], N, p=[.5, .4, .1])
f["floor_level"] = np.where(rng.random(N) < .5, rng.integers(0, 30, N), np.nan)
f["block_homes_2026"] = rng.integers(50, 400, N)
f["block_new_homes_2021_2026"] = rng.integers(0, 80, N)
f["latitude"], f["longitude"] = f["lat"], f["lon"]
f["mb"] = 1; f["address"] = f["building_address"]; f["property_type"] = "unit"
f["car_spaces"] = f["car_space"]; f["ever_advertised_for_lease"] = 1
f["first_ever_listed"] = ""; f["attrs_last_seen"] = ""


def true_rent(r, car, days_before):
    return (base[r.suburb] + 230 * r.bedrooms + 60 * (r.bathrooms - 1) + 45 * car
            + 4 * np.nan_to_num(r.floor_level, nan=5) + r.bq) * (1 - 0.00012 * days_before)


cols = ["gnaf_id", "address", "building_address", "suburb", "mb", "latitude", "longitude", "property_type",
        "bedrooms", "bathrooms", "car_space", "car_spaces", "floor_level", "flats_in_building",
        "block_new_homes_2021_2026", "block_homes_2026", "ever_advertised_for_lease", "first_ever_listed", "attrs_last_seen"]
f[cols].to_csv(out / "rents-input-flats-city-of-sydney.csv", index=False)

ads = f.sample(12000, replace=True, random_state=2).reset_index(drop=True)
dates = pd.Timestamp("2023-01-01") + pd.to_timedelta(rng.integers(0, 1400, len(ads)), unit="D")  # some after Jul 2026 on purpose
days = (pd.Timestamp("2026-07-31") - dates).days.values
car = ads["car_space"].fillna(0).values
rent = [true_rent(r, c, d) for r, c, d in zip(ads.itertuples(), car, days)]
rent = np.round(np.array(rent) * rng.lognormal(0, .08, len(ads)) / 5) * 5
pd.DataFrame({"gnaf_id": ads["gnaf_id"], "attributes.weekly_rent": rent, "listing_date": dates.strftime("%Y-%m-%d"),
              "attributes.bedrooms": ads["bedrooms"], "attributes.bathrooms": ads["bathrooms"],
              "attributes.car_spaces": np.where(rng.random(len(ads)) < .15, np.nan, car),
              "latitude": ads["lat"], "longitude": ads["lon"], "_suburb_queried": ads["suburb"]}
             ).to_csv(out / "rent_adverts.csv", index=False)
print("fake data written to", out)
