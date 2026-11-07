"""Pull past rent adverts for every City of Sydney suburb from the Microburbs hackathon API.

Usage (key stays in the environment, never in the code):
    export MICROBURBS_API_KEY=...            # Windows PowerShell: $env:MICROBURBS_API_KEY="..."
    pip install requests pandas
    python pull_rents.py test                # step 1: one call, prints the response shape
    python pull_rents.py all                 # step 2: every suburb, written to rent_adverts.csv

Date rule: the task is as at 31 July 2026, so we ALWAYS pass to_date=2026-07-31.
The Aug-Sep 2026 adverts are the frozen test set; this script never downloads them.
"""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

BASE = "https://api-ht.microburbs.com.au"
KEY = os.environ.get("MICROBURBS_API_KEY")
TO_DATE = "2026-07-31"          # task as-at date. Do not change.
PAGE = 1000                     # API max per page
RAW_DIR = Path("raw")           # raw JSON per page, so nothing needs re-downloading
RAW_DIR.mkdir(exist_ok=True)

if not KEY:
    sys.exit("Set MICROBURBS_API_KEY first (see the top of this file).")

S = requests.Session()
S.headers["Authorization"] = f"Bearer {KEY}"


def get(path, **params):
    """GET with retry on 429/5xx. Returns the full JSON body (data + meta)."""
    url = BASE + quote(path, safe="/")
    for attempt in range(6):
        r = S.get(url, params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} {path}: {r.text[:300]}")
        time.sleep(0.12)        # stay under 10 requests/second
        return r.json()
    raise RuntimeError(f"gave up on {path}")


def rows_of(body):
    """Find the list of adverts inside the response, whatever it is called."""
    data = body.get("data") if isinstance(body, dict) else body
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "listings", "adverts", "results", "rows", "data"):
            if isinstance(data.get(k), list):
                return data[k]
        lists = [v for v in data.values() if isinstance(v, list)]
        if lists:
            return max(lists, key=len)
    return []


def suburb_names():
    body = get("/v1/suburbs/list")
    data = body.get("data")
    names = []
    for item in data if isinstance(data, list) else rows_of(body):
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            n = item.get("area_name") or item.get("name") or item.get("suburb")
            if n:
                names.append(n)
    return sorted(set(names))


def pull_suburb(name):
    out, offset = [], 0
    while True:
        body = get(f"/v1/suburbs/{name}/listings/rent-history",
                   to_date=TO_DATE, limit=PAGE, offset=offset)
        (RAW_DIR / f"{name.replace(' ', '_').replace('/', '-')}_{offset}.json").write_text(json.dumps(body))
        rows = rows_of(body)
        for r in rows:
            r["_suburb_queried"] = name
        out += rows
        if len(rows) < PAGE:
            return out
        offset += PAGE


def main(mode):
    if mode == "test":
        name = "Surry Hills"
        body = get(f"/v1/suburbs/{name}/listings/rent-history",
                   to_date=TO_DATE, limit=3)
        print("TOP-LEVEL KEYS:", list(body.keys()) if isinstance(body, dict) else type(body))
        print(json.dumps(body, indent=2)[:3000])
        print("\nSuburb list sample:", suburb_names()[:40])
        return
    names = suburb_names()
    print(len(names), "suburbs")
    allrows = []
    for i, n in enumerate(names, 1):
        try:
            rows = pull_suburb(n)
        except Exception as e:
            print(f"[{i}/{len(names)}] {n}: FAILED {e}")
            continue
        print(f"[{i}/{len(names)}] {n}: {len(rows)} adverts")
        allrows += rows
    df = pd.json_normalize(allrows)
    df.to_csv("rent_adverts.csv", index=False)
    print("wrote rent_adverts.csv", df.shape)
    # sanity check on the date rule: nothing may be later than 31 July 2026
    for c in df.columns:
        if "date" in c.lower() or "listed" in c.lower():
            d = pd.to_datetime(df[c], errors="coerce")
            if d.notna().any():
                print(f"{c}: {d.min().date()} -> {d.max().date()}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test")
