"""Build report.html from outputs/metrics.json and outputs/figs/*.png.

    python src/build_report.py
"""
import base64
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

m = json.loads((C.OUT / "metrics.json").read_text())
ins = m["insights"]
W = m["windows"]
enc = m["encoding"]


def money(x):
    return f"${x:,.0f}"


def img(name, alt):
    p = C.FIGS / name
    if not p.exists():
        return ""
    b = base64.b64encode(p.read_bytes()).decode()
    return f'<figure><img src="data:image/png;base64,{b}" alt="{html.escape(alt)}"><figcaption>{html.escape(alt)}</figcaption></figure>'


def row(name, s):
    return (f"<tr><td>{name}</td><td>{money(s['median_abs_error'])}</td><td>{s['within_100']*100:.1f}%</td>"
            f"<td>{s['r2']:.3f}</td><td>{money(s['mean_abs_error'])}</td><td>{s['median_bias']:+.0f}</td><td>{s['n']:,}</td></tr>")


pb = ins["parking_premium_by_beds"]
ps = list(ins["parking_premium_by_suburb"].items())
fi = list(m["feature_importance"].items())[:10]
ri = m["rent_index"]
trough = min(ri, key=ri.get)
sp = m["split"]
bench = m["benchmarks_from_task_page"]
cl = m["cleaning"]
mA, mB, m2 = W[f"{enc}/A"]["model"], W[f"{enc}/B"]["model"], W[f"{enc}/A_2months"]["model"]

INSIGHTS = [
    f"Typical error ${mA['median_abs_error']:.1f} a week, with {mA['within_100']*100:.1f}% of estimates within $100, on {mA['n']:,} held-out "
    f"May–July 2026 adverts, scored through the exact pipeline that produced our submission. An earlier window (Feb–Apr 2026) gives "
    f"${mB['median_abs_error']:.1f} and {mB['within_100']*100:.1f}%. The suburb × bedrooms median scores $100 and about 56% in both.",
    f"Three signals carry most of the accuracy: what similar-sized flats in the same ABS block and the same building have rented for, "
    f"and the flat's own last advert. {ins['flats_with_own_history']*100:.0f}% of the 65,777 flats have been advertised before; for those our "
    f"typical error is {money(m['model_flat_seen_before']['median_abs_error'])}, against "
    f"{money(m['model_flat_never_advertised']['median_abs_error'])} for flats with no earlier advert in our data.",
    f"The median gap between our with- and without-car-space estimates is {money(ins['parking_premium_median'])} a week: "
    f"{money(pb.get('0', 0))} for studios, {money(pb.get('2', 0))} for two bedrooms, {money(pb.get('3', 0))} for three. "
    f"It is widest near the harbour ({html.escape(ps[0][0])} {money(ps[0][1])}, {html.escape(ps[1][0])} {money(ps[1][1])}). "
    f"These are model estimates, not measured prices of a car space.",
    f"Same-flat rents bottomed out in {trough} at about {ri[trough]*100:.0f}% of July 2026's level, and rose "
    f"{m['annual_rent_growth']*100:.1f}% in the year to July 2026. A flat that last rented at the 2020–21 low can be worth far more now, "
    f"so we bring every past advert to July 2026 dollars before learning from it.",
    f"Raising floor level by five changes our model's estimates by about ${ins['rent_per_extra_floor']:.2f} per floor on average, once the building is known. "
    f"That is a sensitivity of the model, not a measured floor premium; floor level is missing for about half the flats.",
]

grid_rows = "".join(
    f"<tr><td>{k.replace('mult=', '× ').replace('offset=', '$ ')}</td><td>${v['A']['median_abs_error']:.1f} / {v['A']['within_100']*100:.1f}%</td>"
    f"<td>${v['B']['median_abs_error']:.1f} / {v['B']['within_100']*100:.1f}%</td></tr>" for k, v in m["calibration_grid"].items()
    if k != "offset=0")
win_rows = "".join(
    f"<tr><td>{'Leave-one-out' if e == 'loo' else 'Past-only'} building/block averages{' (chosen)' if e == enc else ''}</td>"
    + "".join(f"<td>${W[f'{e}/{w}']['model']['median_abs_error']:.1f} / {W[f'{e}/{w}']['model']['within_100']*100:.1f}%</td>" for w in ("A", "A_2months", "B"))
    + "</tr>" for e in ("loo", "past"))
win_rows += ("<tr><td>Suburb × bedrooms median</td>" + "".join(
    f"<td>{money(W[f'{enc}/{w}']['baseline_suburb_beds_median']['median_abs_error'])} / {W[f'{enc}/{w}']['baseline_suburb_beds_median']['within_100']*100:.1f}%</td>"
    for w in ("A", "A_2months", "B")) + "</tr>")
by_rows = "".join(row(lbl, m[k]) for k, lbl in [
    ("model_with_car", "Adverts with a car space"), ("model_no_car", "Adverts without a car space"),
    ("model_flat_seen_before", "Flat advertised before"), ("model_flat_never_advertised", "No earlier advert in our data")])
beds_rows = "".join(f"<tr><td>{'studio' if k == '0' else k}</td><td>{money(ins['median_rent_no_car_by_beds'][k])}</td><td>{money(v)}</td></tr>"
                    for k, v in pb.items() if int(k) <= 4)
sub_prem = "".join(f"<tr><td>{html.escape(k)}</td><td>{money(v)}</td></tr>" for k, v in ps[:8])
fi_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>+${v:,.2f}</td></tr>" for k, v in fi)
sub_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{money(v)}</td></tr>" for k, v in ins["suburb_median_rent_no_car"].items())

page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>What will this flat rent for? Team 2more</title>
<style>
 body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:920px;margin:2rem auto;padding:0 1.2rem;color:#1f2328;line-height:1.55}}
 h1{{font-size:1.9rem;margin-bottom:.2rem}} h2{{margin-top:2.2rem;border-bottom:1px solid #ddd;padding-bottom:.3rem}}
 .sub{{color:#57606a}} .kpis{{display:flex;gap:1rem;flex-wrap:wrap;margin:1.2rem 0}}
 .kpi{{flex:1;min-width:150px;border:1px solid #ddd;border-radius:10px;padding:.8rem 1rem}}
 .kpi b{{display:block;font-size:1.6rem}} table{{border-collapse:collapse;width:100%;margin:.8rem 0;font-size:.93rem}}
 td,th{{border-bottom:1px solid #eee;padding:.4rem .5rem;text-align:left}} th{{background:#f6f8fa}}
 figure{{margin:1rem 0}} img{{max-width:100%}} figcaption{{color:#57606a;font-size:.85rem}}
 .note{{background:#f6f8fa;border-left:4px solid #888;padding:.6rem 1rem}}
</style></head><body>
<h1>What will this flat rent for?</h1>
<p class="sub">Team 2more · Microburbs Hackathon, Task 4 · weekly asking rent for {m['outputs']['rows']:,} City of Sydney flats, with and without a car space, as at 31 July 2026</p>

<div class="kpis">
 <div class="kpi"><b>{money(mA['median_abs_error'])}</b>typical error, held-out May–Jul 2026</div>
 <div class="kpi"><b>{mA['within_100']*100:.1f}%</b>within $100</div>
 <div class="kpi"><b>{mA['r2']:.2f}</b>R² on held-out adverts</div>
 <div class="kpi"><b>{money(ins['parking_premium_median'])}</b>median with/without car-space gap</div>
</div>

<h2>What we found</h2>
<ol>{"".join(f"<li>{t}</li>" for t in INSIGHTS)}</ol>

<h2>How accurate is it?</h2>
<p>Each check re-runs the <b>exact submission pipeline</b> as if the date were the cut-off: rebuild the rent index and every history feature from earlier adverts only,
fit the model, price all 65,777 input flats from their input records, apply the same rounding and parking rule, then join to the later adverts by flat.
Each advert is scored against the column matching its parking (the advert's, else the flat's record; dropped only if both are unknown), as the task specifies.</p>
<table><tr><th>Window A: built to {sp['train_to']}, tested {sp['val_from']} to {sp['val_to']}</th><th>Median abs. error</th><th>Within $100</th><th>R²</th><th>Mean abs. error</th><th>Median bias</th><th>Adverts</th></tr>
{row("<b>Our model</b>", mA)}{row("Suburb × bedrooms median", m['baseline_suburb_beds_median'])}{by_rows}</table>
<p>Two cut-offs, plus a two-month subset of window A (median error / within $100):</p>
<table><tr><th>Version</th><th>A: May–Jul 2026</th><th>A, May–Jun only (2-month horizon, like the real test)</th><th>B: Feb–Apr 2026</th></tr>{win_rows}</table>
<p>Task benchmarks on the official Aug–Sep 2026 adverts, for context only (a different test set, so not a like-for-like comparison): simple estimate ${bench['simple']}, with parking ${bench['simple_with_parking']},
Microburbs rental valuation ${bench['microburbs_valuation']} ({bench['microburbs_within_100']*100:.1f}% within $100), suburb median {bench['suburb_median_within_100']*100:.1f}% within $100.</p>
{img("actual_vs_pred.png", "Estimate vs advertised rent, held-out window A")}
{img("error_hist.png", "Distribution of errors, held-out window A")}

<h2>How we split adverts by date</h2>
<div class="note">The task is set at 31 July 2026. We drop every advert listed after that date before doing anything else (the code asserts it), and never use the live listings endpoint or the official Aug–Sep adverts.
For our own checks we pretend the date is 1 May 2026 (window A) or 1 February 2026 (window B): everything is learned from earlier adverts and scored on the following three months.
{W[f'{enc}/A']['share_seen']*100:.0f}% of window-A adverts are for flats with an earlier advert, close to the {ins['flats_with_own_history']*100:.0f}% of input flats with one.
Both windows were used to choose between versions below, so they are development checks rather than untouched tests, and the baseline scoring about the same as the task's published benchmark does not show that our sample matches the official one.
In these checks the index is referenced to the last month before the cut (April or January), not July.</div>
<p><b>Known limits of the backtest.</b> (1) Old adverts keep their own recorded bedrooms, bathrooms and parking; we never fill these from the July 2026 input (missing stays missing). Only fixed facts about the address (building, ABS block, floor, block counts) come from the input file. (2) The model trains for a fixed 1,500 iterations on all training adverts (no internal early-stopping split). Building and block averages use adverts from strictly earlier dates, but the rent adjustment uses an index fitted on the whole training period available at each cut-off. (3) The official Aug–Sep scores may differ from ours.</p>

<h2>Choices we tested</h2>
<p><b>Building and block averages.</b> Computing each training advert's building and block averages only from adverts on earlier dates (past-only) beat leave-one-out averages on both windows, so the submission uses past-only. Adverts with no known building get no building average, in training and prediction alike.</p>
<p><b>Two changes from a teammate's independent rebuild.</b> Indra's stricter re-implementation never back-fills old adverts from the July input and trains on all data with a fixed iteration count. Adopting both improved window A from $43.5 to $43.0 and window B from $45.5 to $44.5, so the submission uses them. Scored on the same adverts, Indra's own model was within $1 of ours.</p>
<p><b>Bias correction.</b> The model runs a little high (median bias {mA['median_bias']:+.0f}). Scaling down or subtracting dollars helped window A but hurt window B, so we applied no correction.</p>
<table><tr><th>Adjustment</th><th>Window A</th><th>Window B</th></tr>{grid_rows}</table>
<p>Earlier exploratory checks (in <code>tools/</code>, using an older advert-based validation, not the exact pipeline) found no gain from a fixed 3–8% parking premium or an average of four model variants.</p>

<h2>The car-space gap</h2>
<p>Every flat gets two estimates from the same model, with the car-space flag set to 1 and to 0. The table shows the median gap. Because the flat's own past rent and its building's rents already reflect whether it usually has parking,
flipping the flag is not a clean measure of what a car space is worth, and the gap could be understated or overstated. For {m['parking_gap_clipped_to_zero']:,} flats the raw model gave a lower estimate with parking; we set those gaps to zero, since a car space should not lower rent.
A simple comparison of flats in the same building with the same bedrooms shows about 8% higher advertised rent with parking; some of that may reflect unmeasured size or quality.</p>
<table><tr><th>Bedrooms</th><th>Median estimate, no car space</th><th>Median with/without gap</th></tr>{beds_rows}</table>
<table><tr><th>Suburb (widest gaps)</th><th>Median with/without gap / week</th></tr>{sub_prem}</table>
{img("parking_by_beds.png", "Median with/without car-space gap by bedrooms")}

<h2>Data</h2>
<ul>
 <li>The supplied past-leases file: 112,457 rent adverts for City of Sydney flats, 2012 to 31 July 2026. We use those from 2015 on.</li>
 <li>The supplied flats file (bedrooms, bathrooms, parking, floor, building, ABS block, block homes and new homes).</li>
 <li>Cleaning: {cl['raw_rows']:,} adverts → {cl['from_2015']:,} from 2015 → {cl['usable']:,} usable after removing duplicates and adverts with more than six bedrooms (no rents fell outside $150–$6,000/week).
 Missing bedrooms, bathrooms and parking on an old advert are left missing rather than filled from today's record. Validation adverts skip these training filters.</li>
 <li>{m['input_beds_over_6']} input flats list more than six bedrooms; they are priced like the largest flats in training.</li>
</ul>

<h2>Method</h2>
<ol>
 <li><b>Rent index.</b> A monthly same-flat index (log rent = flat effect + month effect, from flats advertised more than once, smoothed over 3 months). Every past advert is converted to July 2026 dollars. The smoothed endpoint averages June and July, so in a rising market it can lag the very latest level slightly.</li>
 {img("rent_index.png", "Same-flat rent index (July 2026 = 100)")}
 <li><b>Features.</b> Bedrooms, bathrooms, car space, property type, suburb, latitude and longitude, floor, flats in the building, block homes and new homes; the past rents of the same building (overall and same bedrooms) and the same ABS block (same bedrooms); and the flat's own last advert: its adjusted rent, how long ago, and whether it had parking. All history comes from earlier dates only.</li>
 <li><b>Model.</b> Gradient-boosted trees (scikit-learn HistGradientBoosting, 1,500 iterations, no early stopping) on log adjusted rent with absolute-error loss. This is a robust choice checked on dollar-scale validation, not an exact match to the median-dollar-error score.</li>
 <li><b>Two answers per flat.</b> Run the model with the car-space flag at 1 and at 0, never let parking lower the estimate, round to 50 cents, and fall back to the suburb × bedrooms median if anything is missing, so no answer is blank.</li>
</ol>
<table><tr><th>Raw-model permutation importance (window A: increase in median absolute dollar error when the feature is shuffled, before parking clipping and rounding)</th><th></th></tr>{fi_rows}</table>

<h2>Median estimated rent by suburb (no car space)</h2>
<table><tr><th>Suburb</th><th>Median weekly rent</th></tr>{sub_rows}</table>

<p class="sub">Estimates are automated and indicative only. Data © Microburbs and the sources credited in README.md. An independent review of an earlier version prompted the exact-pipeline validation, past-only averages and the calibration test above.</p>
</body></html>"""

(C.ROOT / "report.html").write_text(page, encoding="utf-8")
print("Wrote report.html")
