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
    for k, col in [("beds", "bedrooms"), ("baths", "bathrooms"), ("car", "car_space"),
                   ("building_address", "building_address"), ("mb", "mb")]:
        if col in f.columns:
            a[k] = a[k].fillna(g.map(f[col]))
    a = a.dropna(subset=["beds"])
    a = a[a["beds"] <= 6]
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


def prior_own_train(train):
    """For each training advert: the same flat's previous advert (adjusted rent, days ago, count)."""
    t = train.sort_values("date")
    gb = t.groupby("key")
    out = pd.DataFrame(index=t.index)
    out["own_prev"] = gb["y"].shift(1)
    out["own_prev_age"] = (t["date"] - gb["date"].shift(1)).dt.days
    out["own_n"] = gb.cumcount()
    out["own_prev_car"] = gb["car"].shift(1)
    return out.reindex(train.index)


def prior_own_from(history, target, as_of):
    """For target flats: last advert in `history` (all dated before as_of)."""
    last = history.sort_values("date").groupby("key").agg(
        own_prev=("y", "last"), last_date=("date", "last"), own_n=("y", "size"), own_prev_car=("car", "last"))
    m = target[["key"]].join(last, on="key")
    out = pd.DataFrame(index=target.index)
    out["own_prev"] = m["own_prev"].values
    out["own_prev_age"] = (as_of - m["last_date"]).dt.days.values
    out["own_n"] = m["own_n"].fillna(0).values
    out["own_prev_car"] = m["own_prev_car"].values
    return out


GROUPS = [("bb", ["building_address", "beds"]), ("b", ["building_address"]), ("mbb", ["mb", "beds"])]


def features(df, history, codes, mode, as_of=None):
    """mode='train' (leave-one-out on history==df) or 'apply' (history strictly earlier)."""
    X = pd.DataFrame(index=df.index)
    for c in ["beds", "baths", "car", "lat", "lon", "floor_level", "flats_in_building",
              "block_new_homes_2021_2026", "block_homes_2026"]:
        X[c] = pd.to_numeric(df[c], errors="coerce")
    X["suburb"] = df["suburb_n"].map(codes["suburb"]).astype(float)
    X["ptype"] = df["ptype_n"].map(codes["ptype"]).astype(float)
    for name, keys in GROUPS:
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
        early_stopping=True, validation_fraction=0.1, n_iter_no_change=50, random_state=0)


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

    # ---------------- validation, everything learned before the cut
    cut = pd.Timestamp(C.VAL_START)
    tr = adv[adv["date"] < cut].copy()
    va = adv[adv["date"] >= cut].copy()
    va = va[va["car"].notna()]                                  # scorer drops adverts with unknown parking
    idx_tr = rent_index(tr)
    tr["y"] = apply_index(tr, idx_tr)
    va["y"] = np.nan
    as_of_tr = tr["date"].max()
    print(f"Train {len(tr)} adverts (to {as_of_tr.date()}), validate {len(va)} ({va['date'].min().date()} -> {va['date'].max().date()})")
    Xtr = features(tr, tr, codes, "train")
    Xva = features(va, tr, codes, "apply", as_of=as_of_tr)
    m = new_model(list(Xtr.columns)).fit(Xtr, tr["y"])
    pv = np.exp(m.predict(Xva))                                 # in last-training-month dollars, like the real task
    pb = baseline_predict(tr, va)
    yv = va["rent"].values
    metrics = {
        "cleaning": log,
        "split": {"train_rows": int(len(tr)), "val_rows": int(len(va)), "train_to": str(as_of_tr.date()),
                  "val_from": str(va["date"].min().date()), "val_to": str(va["date"].max().date())},
        "model": score(yv, pv),
        "baseline_suburb_beds_median": score(yv, pb),
        "benchmarks_from_task_page": {"simple": 100, "simple_with_parking": 93, "microburbs_valuation": 86,
                                      "microburbs_within_100": 0.5521, "suburb_median_within_100": 0.5639},
    }
    seen = Xva["own_prev"].notna().values
    metrics["model_flat_seen_before"] = score(yv[seen], pv[seen])
    metrics["model_flat_never_advertised"] = score(yv[~seen], pv[~seen])
    for flag, name in [(1.0, "with_car"), (0.0, "no_car")]:
        s = (va["car"] == flag).values
        if s.sum() > 30:
            metrics[f"model_{name}"] = score(yv[s], pv[s])
    for k in ["model", "baseline_suburb_beds_median", "model_flat_seen_before", "model_flat_never_advertised"]:
        print(f"VALIDATION {k:30s}", {a: round(b, 3) for a, b in metrics[k].items()})

    sub = Xva.sample(min(3000, len(Xva)), random_state=0)
    ysub = np.log(va.loc[sub.index, "rent"])
    pi = permutation_importance(m, sub, ysub, scoring="neg_median_absolute_error", n_repeats=3, random_state=0)
    metrics["feature_importance"] = dict(sorted(
        {c: float(v) * 100 for c, v in zip(Xtr.columns, pi.importances_mean)}.items(), key=lambda kv: -kv[1]))

    # ---------------- final fit on everything up to 31 July 2026
    idx = rent_index(adv)
    adv["y"] = apply_index(adv, idx)
    yr = idx[idx.index >= idx.index[-1] - 12]
    metrics["annual_rent_growth"] = float(np.exp(yr.iloc[-1] - yr.iloc[0]) - 1)
    metrics["rent_index"] = {str(k): float(np.exp(v)) for k, v in idx.items()}
    Xall = features(adv, adv, codes, "train")
    final = new_model(list(Xall.columns)).fit(Xall, adv["y"])

    Xp = features(target, adv, codes, "apply", as_of=AS_AT)
    Xw, Xo = Xp.copy(), Xp.copy()
    Xw["car"], Xo["car"] = 1.0, 0.0
    for X in (Xw, Xo):
        X["own_car_changed"] = (X["own_prev_car"] != X["car"]).astype(float).where(X["own_prev_car"].notna())
    pw, po = np.exp(final.predict(Xw)), np.exp(final.predict(Xo))
    pw = np.maximum(pw, po)
    fb = baseline_predict(adv, target)
    pw = np.where(np.isfinite(pw), pw, fb)
    po = np.where(np.isfinite(po), po, fb)

    out = pd.DataFrame({"gnaf_id": inp["gnaf_id"],
                        "rent_with_car_space": np.round(pw * 2) / 2,
                        "rent_without_car_space": np.round(po * 2) / 2})
    assert out["gnaf_id"].is_unique and len(out) == len(inp)
    assert out.iloc[:, 1:].notna().all().all() and (out.iloc[:, 1:] > 0).all().all()
    out.to_csv(C.FILE_OUT, index=False, encoding="utf-8")
    print(f"Wrote {C.FILE_OUT.name}: {len(out)} rows")

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
    ins["rent_per_extra_floor"] = float(np.median(np.exp(final.predict(Xu)) - po[k.values]) / 5)
    # floor effect on the raw adverts too (same building + beds, adjusted rent vs floor)
    metrics["insights"] = ins
    metrics["outputs"] = {"rows": int(len(out)), "file": C.FILE_OUT.name}

    # ---------------- figures
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

    s = pd.Series(ins["parking_premium_by_beds"]).sort_index()
    fig, ax = plt.subplots(figsize=(5, 3.5)); ax.bar(s.index, s.values)
    ax.set_xlabel("Bedrooms"); ax.set_ylabel("Median car-space premium ($/week)")
    fig.tight_layout(); fig.savefig(C.FIGS / "parking_by_beds.png", dpi=130); plt.close(fig)

    ri = pd.Series(metrics["rent_index"]); ri.index = pd.PeriodIndex(ri.index, freq="M").to_timestamp()
    fig, ax = plt.subplots(figsize=(6.5, 3.2)); ax.plot(ri.index, ri.values * 100)
    ax.set_ylabel("Rent index (Jul 2026 = 100)"); ax.set_title("Same-flat rent index, City of Sydney flats")
    fig.tight_layout(); fig.savefig(C.FIGS / "rent_index.png", dpi=130); plt.close(fig)

    (C.OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print("Wrote outputs/metrics.json and figures. Next: python src/build_report.py")


if __name__ == "__main__":
    main()
