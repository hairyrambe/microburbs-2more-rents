"""Second held-out window + small ensemble test. Everything learned before each cut."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, 'src'); import build_model as B
from sklearn.ensemble import HistGradientBoostingRegressor
raw, _ = B.load_adverts(); inp = B.load_input(); adv, _ = B.clean_adverts(raw, inp); tgt = B.prep_input(inp)
codes = {"suburb": {s: i for i, s in enumerate(sorted(set(adv.suburb_n) | set(tgt.suburb_n)))},
         "ptype": {s: i for i, s in enumerate(sorted(set(adv.ptype_n) | set(tgt.ptype_n)))}}
def variant(cols, lr, leaves, seed):
    return HistGradientBoostingRegressor(loss="absolute_error", learning_rate=lr, max_iter=1500, max_leaf_nodes=leaves,
        min_samples_leaf=30, l2_regularization=1.0, categorical_features=[c in ("suburb","ptype") for c in cols],
        early_stopping=True, validation_fraction=0.1, n_iter_no_change=50, random_state=seed)
def s(y, p): e = np.abs(p - y); return f"${np.median(e):.1f} | {100*(e<=100).mean():.1f}% within $100"
for start, end in [("2026-02-01", "2026-04-30"), ("2026-05-01", "2026-07-31")]:
    tr = adv[adv.date < start].copy(); va = adv[(adv.date >= start) & (adv.date <= end) & adv.car.notna()].copy()
    tr["y"] = B.apply_index(tr, B.rent_index(tr)); va["y"] = np.nan
    Xtr = B.features(tr, tr, codes, "train"); Xva = B.features(va, tr, codes, "apply", as_of=tr.date.max())
    y = va.rent.values; cols = list(Xtr.columns); preds = []
    for lr, leaves, seed in [(0.05, 63, 0), (0.05, 63, 1), (0.03, 127, 2), (0.08, 31, 3)]:
        p = np.exp(variant(cols, lr, leaves, seed).fit(Xtr, tr.y).predict(Xva)); preds.append(p)
        print(f"{start}..{end} n={len(va)} single lr={lr} leaves={leaves}: {s(y, p)}")
    print(f"{start}..{end} ENSEMBLE of 4 (median): {s(y, np.median(preds, axis=0))}   baseline: {s(y, B.baseline_predict(tr, va))}\n")
