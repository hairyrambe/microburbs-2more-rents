"""Task 4 pipeline: weekly rent for every flat, with and without a car space.

    python src/build_model.py --inspect     # show columns found + mapping, then stop
    python src/build_model.py               # validate, fit, predict, write rents_2more.csv

Honest-evaluation rules baked in:
  * every advert dated after 2026-07-31 is dropped (hard assert);
  * validation: everything (rent index, building/flat history, model) is learned from adverts
    before VAL_START only, and predictions are made "as at" the last training month,
    exactly like the real test (built at 31 Jul, scored on later adverts);
  * the official frozen Aug-Sep adverts are never touched (we do not have them).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import r2_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

AS_AT = pd.Timestamp(C.AS_AT)
FILL_CHANGEABLE_FROM_INPUT = False  # fill an old advert's beds/baths/parking from the July 2026 input record?
EARLY_STOPPING = False              # False = fixed 1,500 iterations on 100% of training adverts
INDEX_FROM = pd.Timestamp("2015-01-01")    # adverts older than this are too stale to help


# ----------------------------------------------------------------------------- loading
def pick(df, key):
    if key in C.OVERRIDES:
        return C.OVERRIDES[key]
    low = {c: c.lower().split(".")[-1] for c in df.columns}
    for cand in C.CANDIDATES[key]:
        for raw, short in low.items():
            if short == cand:
                return raw
    return None


def norm_suburb(s):
    return s.astype(str).str.lower().str.replace(r"\(.*?\)", "", regex=True).str.strip()


def standardise(df, source):
    out = pd.DataFrame(index=df.index)
    mapping = {}
    for key in C.CANDIDATES:
        raw = pick(df, key)
        mapping[key] = raw
        out[key] = df[raw] if raw else np.nan
    for extra in ("building_address", "mb", "address"):
        out[extra] = df[extra] if extra in df.columns else np.nan
    out["source"] = source
    return out, mapping


def load_adverts():
    frames, maps = [], {}
    for path, tag in [(C.FILE_PAST_LEASES, "supplied"), (C.FILE_API_ADVERTS, "api")]:
        if path.exists():
            raw = pd.read_csv(path, low_memory=False)
            std, m = standardise(raw, tag)
            frames.append(std)
            maps[tag] = {"file": path.name, "rows": len(raw), "mapping": m}
    if not frames:
        sys.exit("No advert files found in data/.")
    return pd.concat(frames, ignore_index=True), maps


def load_input():
    if not C.FILE_INPUT.exists():
        sys.exit(f"Missing {C.FILE_INPUT.name} in data/")
    return pd.read_csv(C.FILE_INPUT, low_memory=False)


# ----------------------------------------------------------------------------- cleaning
def clean_adverts(a, inp):
    log = {"raw_rows": int(len(a))}
    a = a.copy()
    a["date"] = pd.to_datetime(a["date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    for c in ["rent", "beds", "baths", "lat", "lon", "car", "mb"]:
        a[c] = pd.to_numeric(a[c], errors="coerce")
    a["car"] = np.where(a["car"].isna(), np.nan, (a["car"] > 0).astype(float))
    a = a.dropna(subset=["rent", "date"])
    a = a[a["date"] <= AS_AT]
    assert a["date"].max() <= AS_AT, "advert after 31 Jul 2026 slipped through"
    log["after_date_rule"] = int(len(a))
    a = a[a["date"] >= INDEX_FROM]
    log["from_2015"] = int(len(a))
    a = a[(a["rent"] >= 150) & (a["rent"] <= 6000)]
    log["after_rent_sanity"] = int(len(a))
    a = a.drop_duplicates(subset=["gnaf", "date", "rent"])
    log["after_dedupe"] = int(len(a))

    # fill gaps from the flat's own record in the input file (same rule the scorer uses for parking)
    f = inp.set_index("gnaf_id")
    g = a["gnaf"]
    a["mb"] = a["mb"].astype(float)
    fills = [("building_address", "building_address"), ("mb", "mb")]          # fixed facts about the address
    if FILL_CHANGEABLE_FROM_INPUT:
        fills += [("beds", "bedrooms"), ("baths", "bathrooms"), ("car", "car_space")]
    for k, col in fills:
        if col in f.columns:
            a[k] = a[k].fillna(g.map(f[col]))
    a["car"] = np.where(a["car"].isna(), np.nan, (a["car"] > 0).astype(float))   # re-normalise after filling
    if FILL_CHANGEABLE_FROM_INPUT:
        a = a.dropna(subset=["beds"])
    a = a[a["beds"].isna() | (a["beds"] <= 6)]
    log["usable"] = int(len(a))

    for c in ["floor_level", "flats_in_building", "block_new_homes_2021_2026", "block_homes_2026"]:
        a[c] = g.map(f[c]) if c in f.columns else np.nan
    a["suburb_n"] = norm_suburb(a["suburb"])
    a["ptype_n"] = a["ptype"].astype(str).str.lower()
    a["month"] = a["date"].dt.to_period("M")
    a["key"] = a["gnaf"].fillna(a["address"]).astype(str)
    return a.sort_values("date").reset_index(drop=True), log


# ----------------------------------------------------------------------------- rent index
def rent_index(df, iters=30):
    """Monthly log-rent index from repeat adverts: log(rent) = flat effect + month effect.
    Solved by alternating demeaning. Returns month -> log index, last month = 0, smoothed."""
    y = np.log(df["rent"].values)
    key, month = df["key"].values, df["month"].values
    m_eff = pd.Series(0.0, index=df.index)
    for _ in range(iters):
        f_eff = pd.Series(y - m_eff.values).groupby(key).transform("mean")
        m_eff = pd.Series(y - f_eff.values).groupby(month).transform("mean")
    idx = pd.Series(m_eff.values, index=month).groupby(level=0).mean().sort_index()
    full = pd.period_range(idx.index.min(), idx.index.max(), freq="M")
    idx = idx.reindex(full).interpolate().rolling(3, center=True, min_periods=1).mean()
    return idx - idx.iloc[-1]


def apply_index(df, idx):
    v = df["month"].map(idx)
    v = v.fillna(0.0)  # months after the index ends are treated as the last month
    return np.log(df["rent"].values) - v.values


# ----------------------------------------------------------------------------- history features
def group_stats(train, target, keys, name, loo):
    """Mean adjusted log rent of a group (building, block...) learned from `train`."""
    g = train.groupby(keys)["y"].agg(["sum", "count"]).reset_index()
    m = target[keys].merge(g, on=keys, how="left")
    s, n = m["sum"].values.astype(float), m["count"].values.astype(float)
    if loo:
        s, n = s - target["y"].values, n - 1
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, s / n, np.nan)
    return pd.DataFrame({f"{name}_mean": mean, f"{name}_n": np.nan_to_num(n)}, index=target.index)


def group_stats_past(df, keys, name):
    """Mean adjusted log rent of the group from adverts on strictly EARLIER dates (date-blocked)."""
    d = df[keys + ["date", "y"]].copy()
    # rows with a missing key (e.g. unknown building) get no group mean, exactly as at prediction time
    agg = d.groupby(keys + ["date"])["y"].agg(["sum", "count"]).reset_index().sort_values("date")
    g = agg.groupby(keys)
    agg["cs"] = g["sum"].cumsum() - agg["sum"]
    agg["cn"] = g["count"].cumsum() - agg["count"]
    m = d[keys + ["date"]].merge(agg[keys + ["date", "cs", "cn"]], on=keys + ["date"], how="left")
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(m["cn"].values > 0, m["cs"].values / m["cn"].values, np.nan)
    return pd.DataFrame({f"{name}_mean": mean, f"{name}_n": m["cn"].fillna(0).values}, index=df.index)


def prior_own_train(train):
    """For each training advert: the same flat's previous advert (adjusted rent, days ago, count)."""
    # one row per flat per date (the last advert that day), then step back one DATE, not one row,
    # so an advert never "remembers" another advert from the same day
    t = train.sort_values("date")
    day = t.groupby(["key", "date"]).agg(y=("y", "last"), car=("car", "last"), n=("y", "size")).reset_index()
    g = day.groupby("key")
    day["own_prev"] = g["y"].shift(1)
    day["prev_date"] = g["date"].shift(1)
    day["own_prev_car"] = g["car"].shift(1)
    day["own_n"] = g["n"].cumsum() - day["n"]
    m = train[["key", "date"]].merge(day[["key", "date", "own_prev", "prev_date", "own_prev_car", "own_n"]],
                                     on=["key", "date"], how="left")
    out = pd.DataFrame(index=train.index)
    out["own_prev"] = m["own_prev"].values
    out["own_prev_age"] = (m["date"] - m["prev_date"]).dt.days.values
    out["own_n"] = m["own_n"].values
    out["own_prev_car"] = m["own_prev_car"].values
    return out


def prior_own_from(history, target, as_of):
    """For target flats: last advert in `history` (all dated before as_of)."""
    h = history.sort_values("date")
    last = h.groupby("key").tail(1).set_index("key")[["y", "date", "car"]].rename(
        columns={"y": "own_prev", "date": "last_date", "car": "own_prev_car"})
    last["own_n"] = h.groupby("key").size()
    m = target[["key"]].join(last, on="key")
    out = pd.DataFrame(index=target.index)
    out["own_prev"] = m["own_prev"].values
    out["own_prev_age"] = (as_of - m["last_date"]).dt.days.values
    out["own_n"] = m["own_n"].fillna(0).values
    out["own_prev_car"] = m["own_prev_car"].values
    return out


# building keys include the suburb: some street addresses repeat across suburbs
GROUPS = [("bb", ["suburb_n", "building_address", "beds"]), ("b", ["suburb_n", "building_address"]), ("mbb", ["mb", "beds"])]


ENCODING = "loo"   # "loo" or "past"; set by main after the comparison


def features(df, history, codes, mode, as_of=None):
    """mode='train' (history==df) or 'apply' (history strictly earlier).
    Training group stats are leave-one-out (ENCODING='loo') or date-blocked past-only ('past')."""
    X = pd.DataFrame(index=df.index)
    for c in ["beds", "baths", "car", "lat", "lon", "floor_level", "flats_in_building",
              "block_new_homes_2021_2026", "block_homes_2026"]:
        X[c] = pd.to_numeric(df[c], errors="coerce")
    X["suburb"] = df["suburb_n"].map(codes["suburb"]).astype(float)
    X["ptype"] = df["ptype_n"].map(codes["ptype"]).astype(float)
    for name, keys in GROUPS:
        if mode == "train" and ENCODING == "past":
            X = X.join(group_stats_past(df, keys, name))
        else:
            X = X.join(group_stats(history, df, keys, name, loo=(mode == "train")))
    own = prior_own_train(df) if mode == "train" else prior_own_from(history, df, as_of)
    X = X.join(own)
    X["own_gap"] = X["own_prev"] - X["bb_mean"]
    X["own_car_changed"] = (X["own_prev_car"] != X["car"]).astype(float).where(X["own_prev_car"].notna())
    return X


def new_model(cols):
    cat = [c in ("suburb", "ptype") for c in cols]
    return HistGradientBoostingRegressor(
        loss="absolute_error", learning_rate=0.05, max_iter=1500, max_leaf_nodes=63, min_samples_leaf=30,
        l2_regularization=1.0, categorical_features=cat,
        early_stopping=EARLY_STOPPING, validation_fraction=0.1, n_iter_no_change=50, random_state=0)


# ----------------------------------------------------------------------------- metrics
def score(y, p):
    err = np.abs(y - p)
    return {"n": int(len(y)), "median_abs_error": float(np.median(err)), "mean_abs_error": float(err.mean()),
            "within_100": float((err <= 100).mean()), "r2": float(r2_score(y, p)),
            "median_bias": float(np.median(p - y))}


def baseline_predict(train, target):
    """Suburb x bedrooms median of recent (12-month) adverts, falling back to suburb, then global."""
    t0 = train[train["date"] > train["date"].max() - pd.Timedelta(days=365)]
    g1 = t0.groupby(["suburb_n", "beds"])["rent"].median().rename("m1").reset_index()
    g2 = t0.groupby("suburb_n")["rent"].median().rename("m2").reset_index()
    t = target[["suburb_n", "beds"]].merge(g1, on=["suburb_n", "beds"], how="left").merge(g2, on="suburb_n", how="left")
    return t["m1"].fillna(t["m2"]).fillna(t0["rent"].median()).values


def prep_input(inp):
    d = inp.copy()
    d["gnaf"] = d["gnaf_id"]
    d["key"] = d["gnaf_id"].astype(str)
    d["suburb_n"] = norm_suburb(d["suburb"])
    d["ptype_n"] = d["property_type"].astype(str).str.lower()
    d["beds"] = pd.to_numeric(d["bedrooms"], errors="coerce")
    d["baths"] = pd.to_numeric(d["bathrooms"], errors="coerce")
    d["lat"], d["lon"] = d["latitude"], d["longitude"]
    d["car"] = pd.to_numeric(d["car_space"], errors="coerce")
    d["mb"] = pd.to_numeric(d["mb"], errors="coerce").astype(float)
    return d


# ----------------------------------------------------------------------------- one prediction path
def two_preds(model, Xp):
    Xw, Xo = Xp.copy(), Xp.copy()
    Xw["car"], Xo["car"] = 1.0, 0.0
    for X in (Xw, Xo):
        X["own_car_changed"] = (X["own_prev_car"] != X["car"]).astype(float).where(X["own_prev_car"].notna())
    return np.exp(model.predict(Xw)), np.exp(model.predict(Xo)), Xw, Xo


def finalise(pw, po, fb):
    """Exactly what goes into the CSV: fallback, car space never lowers rent, round to 50c."""
    pw = np.where(np.isfinite(pw), pw, fb)
    po = np.where(np.isfinite(po), po, fb)
    pw = np.maximum(pw, po)
    return np.round(pw * 2) / 2, np.round(po * 2) / 2


def predict_flats(hist, target, codes, as_of=None):
    """Fit on `hist` (all adverts before some date) and price every INPUT flat, as at that date."""
    hist = hist.copy()
    as_of = as_of if as_of is not None else hist["date"].max()
    idx = rent_index(hist)
    hist["y"] = apply_index(hist, idx)
    X = features(hist, hist, codes, "train")
    model = new_model(list(X.columns)).fit(X, hist["y"])
    Xp = features(target, hist, codes, "apply", as_of=as_of)
    pw, po, Xw, Xo = two_preds(model, Xp)
    fb = baseline_predict(hist, target)
    fw, fo = finalise(pw, po, fb)
    return {"n_iter": int(model.n_iter_), "model": model, "Xp": Xp, "Xw": Xw, "Xo": Xo, "pw_raw": pw, "po_raw": po, "fb": fb,
            "pw": fw, "po": fo, "idx": idx, "base": baseline_predict(hist, target), "hist_n": len(hist)}


def holdout_source(raw, inp):
    """Held-out adverts as the scorer would see them: input flats only, no training filters."""
    h = raw[["gnaf", "date", "rent", "car"]].copy()
    h["date"] = pd.to_datetime(h["date"], errors="coerce").dt.normalize()
    h["rent"] = pd.to_numeric(h["rent"], errors="coerce")
    h["car"] = pd.to_numeric(h["car"], errors="coerce")
    h = h.dropna(subset=["date", "rent"]).drop_duplicates()
    h = h[h["gnaf"].isin(set(inp["gnaf_id"]))]
    icar = h["gnaf"].map(inp.set_index("gnaf_id")["car_space"])
    h["park"] = h["car"].where(h["car"].notna(), icar)            # advert parking, else the input record's
    h = h[h["park"].notna()]
    h["park"] = (h["park"] > 0).astype(int)
    return h


def evaluate(res, raw_ho, target, cut, end):
    h = raw_ho[(raw_ho["date"] >= cut) & (raw_ho["date"] <= end)]
    pos = pd.Series(np.arange(len(target)), index=target["gnaf_id"].values)
    i = pos.loc[h["gnaf"].values].values
    park = h["park"].values == 1
    p = np.where(park, res["pw"][i], res["po"][i])
    b = res["base"][i]
    y = h["rent"].values
    seen = res["Xp"]["own_prev"].notna().values[i]
    return {"split": {"train_to": str((pd.Timestamp(cut) - pd.Timedelta(days=1)).date()), "val_from": cut,
                      "val_to": end, "val_rows": int(len(h)), "train_rows": int(res["hist_n"])},
            "model": score(y, p), "baseline_suburb_beds_median": score(y, b),
            "seen": score(y[seen], p[seen]), "unseen": score(y[~seen], p[~seen]),
            "with_car": score(y[park], p[park]), "no_car": score(y[~park], p[~park]),
            "share_seen": float(seen.mean()), "_y": y, "_p": p, "_i": i, "_park": park}


def dollar_importance(res, r, n_repeats=3):
    """Permutation importance in DOLLARS: increase in median absolute dollar error when a feature is shuffled."""
    rng = np.random.default_rng(0)
    X = pd.concat([res["Xw"].iloc[r["_i"][r["_park"]]], res["Xo"].iloc[r["_i"][~r["_park"]]]])
    y = np.concatenate([r["_y"][r["_park"]], r["_y"][~r["_park"]]])
    base = np.median(np.abs(np.exp(res["model"].predict(X)) - y))
    out = {}
    for c in X.columns:
        inc = []
        for _ in range(n_repeats):
            Xs = X.copy()
            Xs[c] = rng.permutation(Xs[c].values)
            inc.append(np.median(np.abs(np.exp(res["model"].predict(Xs)) - y)) - base)
        out[c] = float(np.mean(inc))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    args = ap.parse_args()
    C.OUT.mkdir(exist_ok=True)
    C.FIGS.mkdir(parents=True, exist_ok=True)

    raw, maps = load_adverts()
    inp = load_input()
    for tag, m in maps.items():
        print(f"[{tag}] {m['file']} rows={m['rows']}")
        for k, v in m["mapping"].items():
            print(f"   {k:7s} <- {v}")
    if args.inspect:
        return

    adv, log = clean_adverts(raw, inp)
    print("CLEANING:", json.dumps(log))
    target = prep_input(inp)
    codes = {"suburb": {s: i for i, s in enumerate(sorted(set(adv["suburb_n"]) | set(target["suburb_n"])))},
             "ptype": {s: i for i, s in enumerate(sorted(set(adv["ptype_n"]) | set(target["ptype_n"])))}}

    global ENCODING
    raw_ho = holdout_source(raw, inp)

    # ---------------- validation: the EXACT submission pipeline, re-run as if the date were the cut
    windows = {"A": ("2026-05-01", "2026-07-31"), "A_2months": ("2026-05-01", "2026-06-30"),
               "B": ("2026-02-01", "2026-04-30")}
    results, cache = {}, {}
    for enc in ("loo", "past"):
        ENCODING = enc
        for cut in sorted({w[0] for w in windows.values()}):
            cache[(enc, cut)] = predict_flats(adv[adv["date"] < cut], target, codes)
        for wname, (cut, end) in windows.items():
            r = evaluate(cache[(enc, cut)], raw_ho, target, cut, end)
            results[(enc, wname)] = r
            print(f"VALIDATION enc={enc:4s} window={wname:9s} n={r['model']['n']}  model ${r['model']['median_abs_error']:.1f} "
                  f"{r['model']['within_100']*100:.1f}%  | baseline ${r['baseline_suburb_beds_median']['median_abs_error']:.1f} "
                  f"{r['baseline_suburb_beds_median']['within_100']*100:.1f}%")
    # pre-declared rule: keep leave-one-out unless past-only is better on BOTH main windows
    better = all(results[("past", w)]["model"]["median_abs_error"] < results[("loo", w)]["model"]["median_abs_error"] for w in ("A", "B"))
    ENCODING = "past" if better else "loo"
    print("Chosen encoding:", ENCODING)

    # calibration grid on the chosen pipeline; adopt only if it helps on BOTH windows without losing within-$100
    grid = {}
    for kind, vals in (("mult", [1.0, 0.99, 0.98]), ("offset", [0, -5, -10])):
        for v in vals:
            row = {}
            for w in ("A", "B"):
                r = results[(ENCODING, w)]
                p = r["_p"] * v if kind == "mult" else r["_p"] + v
                row[w] = score(r["_y"], p)
            grid[f"{kind}={v}"] = row
    base = grid["mult=1.0"]
    winners = [k for k, row in grid.items() if k not in ("mult=1.0", "offset=0") and all(
        row[w]["median_abs_error"] < base[w]["median_abs_error"] - 0.5 and row[w]["within_100"] >= base[w]["within_100"] for w in ("A", "B"))]
    calib = min(winners, key=lambda k: sum(grid[k][w]["median_abs_error"] for w in ("A", "B"))) if winners else "mult=1.0"
    for k, row in grid.items():
        print(f"CALIBRATION {k:12s} A ${row['A']['median_abs_error']:.1f} {row['A']['within_100']*100:.1f}%  B ${row['B']['median_abs_error']:.1f} {row['B']['within_100']*100:.1f}%")
    print("Chosen calibration:", calib)

    rA = results[(ENCODING, "A")]
    metrics = {
        "cleaning": log, "encoding": ENCODING, "calibration": calib,
        "split": rA["split"],
        "model": rA["model"], "baseline_suburb_beds_median": rA["baseline_suburb_beds_median"],
        "model_flat_seen_before": rA["seen"], "model_flat_never_advertised": rA["unseen"],
        "model_with_car": rA["with_car"], "model_no_car": rA["no_car"],
        "holdout_share_with_history": rA["share_seen"],
        "windows": {f"{e}/{w}": {k: v for k, v in r.items() if not k.startswith("_")} for (e, w), r in results.items()},
        "calibration_grid": grid,
        "benchmarks_from_task_page": {"simple": 100, "simple_with_parking": 93, "microburbs_valuation": 86,
                                      "microburbs_within_100": 0.5521, "suburb_median_within_100": 0.5639},
    }
    metrics["n_iter_by_fit"] = {f"{e}/{c}": r["n_iter"] for (e, c), r in cache.items()}
    metrics["feature_importance"] = dollar_importance(cache[(ENCODING, "2026-05-01")], rA)

    # ---------------- final: same function, all adverts up to 31 July 2026
    fin = predict_flats(adv, target, codes, as_of=AS_AT)
    metrics["n_iter_by_fit"]["final"] = fin["n_iter"]
    kind, v = calib.split("=")
    v = float(v)
    pw, po = fin["pw_raw"], fin["po_raw"]
    if kind == "mult":
        pw, po = pw * v, po * v
    else:
        pw, po = pw + v, po + v
    pw, po = finalise(pw, po, fin["fb"])
    idx = fin["idx"]
    yr = idx[idx.index >= idx.index[-1] - 12]
    metrics["annual_rent_growth"] = float(np.exp(yr.iloc[-1] - yr.iloc[0]) - 1)
    metrics["rent_index"] = {str(k): float(np.exp(v)) for k, v in idx.items()}
    final, Xp, Xo = fin["model"], fin["Xp"], fin["Xo"]
    po_model = fin["po_raw"]

    out = pd.DataFrame({"gnaf_id": inp["gnaf_id"], "rent_with_car_space": pw, "rent_without_car_space": po})
    assert out["gnaf_id"].is_unique and len(out) == len(inp) and set(out["gnaf_id"]) == set(inp["gnaf_id"])
    assert out.iloc[:, 1:].notna().all().all() and (out.iloc[:, 1:] > 0).all().all()
    assert ((out.iloc[:, 1:] * 2) % 1 == 0).all().all()
    out.to_csv(C.FILE_OUT, index=False, encoding="utf-8")
    print(f"Wrote {C.FILE_OUT.name}: {len(out)} rows")
    # verification files read by the local rent explorer (rent_app.py): it only shows accuracy
    # when the CSV's fingerprint matches the one recorded here
    import hashlib
    iters = 1500 if not EARLY_STOPPING else -1
    (C.ROOT / "history_manifest.json").write_text(json.dumps({
        "model": "2more history model (src/build_model.py)", "iterations": iters, "cutoff": C.AS_AT,
        "prediction_rows": int(len(out)), "prediction_sha256": hashlib.sha256(C.FILE_OUT.read_bytes()).hexdigest()}, indent=2))
    mA_ = rA["model"]
    (C.ROOT / "history_check.json").write_text(json.dumps({
        "n": mA_["n"], "median_absolute_error": mA_["median_abs_error"], "within_100_pct": mA_["within_100"] * 100,
        "r_squared": mA_["r2"], "mean_absolute_error": mA_["mean_abs_error"], "median_bias": mA_["median_bias"],
        "origin": rA["split"]["train_to"], "start": rA["split"]["val_from"], "end": rA["split"]["val_to"], "iterations": iters,
        "classification": "Development check (exact submission pipeline, input flats only); not the hidden judging score"}, indent=2))
    gap = fin["pw_raw"] - fin["po_raw"]
    metrics["parking_gap_clipped_to_zero"] = int((gap < 0).sum())
    metrics["identical_columns"] = int((out["rent_with_car_space"] == out["rent_without_car_space"]).sum())
    metrics["input_beds_over_6"] = int((target["beds"] > 6).sum())

    # ---------------- insights
    d = out.assign(beds=target["beds"].values, suburb=target["suburb"].values)
    d["premium"] = d["rent_with_car_space"] - d["rent_without_car_space"]
    ins = {
        "parking_premium_median": float(d["premium"].median()),
        "parking_premium_by_beds": {str(int(k)): float(v) for k, v in d.groupby("beds")["premium"].median().items()},
        "median_rent_no_car_by_beds": {str(int(k)): float(v) for k, v in d.groupby("beds")["rent_without_car_space"].median().items()},
        "suburb_median_rent_no_car": {k: float(v) for k, v in d.groupby("suburb")["rent_without_car_space"].median().sort_values(ascending=False).items()},
        "parking_premium_by_suburb": {k: float(v) for k, v in d.groupby("suburb")["premium"].median().sort_values(ascending=False).items()},
        "flats_with_own_history": float(Xp["own_prev"].notna().mean()),
    }
    k = Xp["floor_level"].notna()
    Xu = Xo[k].copy()
    Xu["floor_level"] += 5
    ins["rent_per_extra_floor"] = float(np.median(np.exp(final.predict(Xu)) - po_model[k.values]) / 5)
    # floor effect on the raw adverts too (same building + beds, adjusted rent vs floor)
    metrics["insights"] = ins
    metrics["outputs"] = {"rows": int(len(out)), "file": C.FILE_OUT.name}

    # ---------------- figures
    yv, pv = rA["_y"], rA["_p"]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(yv, pv, s=4, alpha=.3)
    lim = [np.quantile(yv, .01), np.quantile(yv, .99)]
    ax.plot(lim, lim, "k--", lw=1); ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel("Advertised weekly rent ($)"); ax.set_ylabel("Model estimate ($)")
    ax.set_title(f"Held-out adverts ({metrics['split']['val_from']} to {metrics['split']['val_to']})")
    fig.tight_layout(); fig.savefig(C.FIGS / "actual_vs_pred.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.hist(np.clip(pv - yv, -400, 400), bins=60)
    ax.axvline(0, color="k", lw=1); ax.set_xlabel("Estimate minus advertised rent ($/week)"); ax.set_ylabel("Adverts")
    fig.tight_layout(); fig.savefig(C.FIGS / "error_hist.png", dpi=130); plt.close(fig)

    s = pd.Series({int(k): v for k, v in ins["parking_premium_by_beds"].items() if int(k) <= 4}).sort_index()
    fig, ax = plt.subplots(figsize=(5, 3.5)); ax.bar(["studio" if k == 0 else str(k) for k in s.index], s.values)
    ax.set_xlabel("Bedrooms"); ax.set_ylabel("Median with/without gap ($/week)")
    fig.tight_layout(); fig.savefig(C.FIGS / "parking_by_beds.png", dpi=130); plt.close(fig)

    ri = pd.Series(metrics["rent_index"]); ri.index = pd.PeriodIndex(ri.index, freq="M").to_timestamp()
    fig, ax = plt.subplots(figsize=(6.5, 3.2)); ax.plot(ri.index, ri.values * 100)
    ax.set_ylabel("Rent index (Jul 2026 = 100)"); ax.set_title("Same-flat rent index, City of Sydney flats")
    fig.tight_layout(); fig.savefig(C.FIGS / "rent_index.png", dpi=130); plt.close(fig)

    (C.OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print("Wrote outputs/metrics.json and figures. Next: python src/build_report.py")


if __name__ == "__main__":
    main()
