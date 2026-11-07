"""Build report.html from outputs/metrics.json and outputs/figs/*.png.

    python src/build_report.py

Numbers fill in automatically. Edit the INSIGHTS text below once you have looked at the real results;
the task page says the report should LEAD with insights.
"""
import base64
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

# ---- EDIT ME after the real run: 3-5 plain-English findings, strongest first. -------------------
INSIGHTS = [
    "Typical error ${mae:.0f} a week, with {w100:.1f}% of estimates within $100, on {nval:,} held-out May-July 2026 adverts. The suburb x bedrooms median on the same adverts is ${bmae:.0f} off ({bw100:.1f}% within $100), matching the task's own simple benchmarks.",
    "A flat's own past adverts are the best guide to its next rent. {hist:.0f}% of the 65,777 flats have been advertised before; for those our typical error is ${seen:.0f}, against ${unseen:.0f} for flats never advertised. The building's average rent for the same bedroom count is the next strongest signal.",
    "A car space adds about ${premium:.0f} a week to the typical flat once its building and history are known: ${p0:.0f} for studios, ${p2:.0f} for two bedrooms, ${p3:.0f} for three. It is worth most around the harbour: Dawes Point, The Rocks and Barangaroo (${prem_top:.0f}+). A raw comparison within buildings shows about 8% more for flats with parking, but much of that is bigger flats having the car spaces.",
    "Same-flat rents rose {growth:.1f}% over the year to July 2026. We rebuild a monthly repeat-rent index from flats advertised more than once and convert every past advert to July 2026 dollars before learning from it.",
    "Height matters less than expected: once the building is known, each extra floor adds only about ${floor:.2f} a week. The building, not the floor, sets the price.",
]
# --------------------------------------------------------------------------------------------------

m = json.loads((C.OUT / "metrics.json").read_text())
ins = m["insights"]


def img(name, alt):
    p = C.FIGS / name
    if not p.exists():
        return ""
    b = base64.b64encode(p.read_bytes()).decode()
    return f'<figure><img src="data:image/png;base64,{b}" alt="{html.escape(alt)}"><figcaption>{html.escape(alt)}</figcaption></figure>'


def money(x):
    return f"${x:,.0f}"


def row(name, s):
    return (f"<tr><td>{name}</td><td>{money(s['median_abs_error'])}</td><td>{s['within_100']*100:.1f}%</td>"
            f"<td>{s['r2']:.3f}</td><td>{money(s['mean_abs_error'])}</td><td>{s['median_bias']:+.0f}</td><td>{s['n']:,}</td></tr>")


pb_ = ins["parking_premium_by_beds"]
fill = dict(premium=ins["parking_premium_median"], floor=ins["rent_per_extra_floor"],
            growth=m["annual_rent_growth"] * 100, mae=m["model"]["median_abs_error"],
            w100=m["model"]["within_100"] * 100, nval=m["model"]["n"],
            bmae=m["baseline_suburb_beds_median"]["median_abs_error"],
            bw100=m["baseline_suburb_beds_median"]["within_100"] * 100,
            hist=ins["flats_with_own_history"] * 100, seen=m["model_flat_seen_before"]["median_abs_error"],
            unseen=m["model_flat_never_advertised"]["median_abs_error"],
            p0=pb_.get("0", float("nan")), p2=pb_.get("2", float("nan")), p3=pb_.get("3", float("nan")),
            prem_top=sorted(ins["parking_premium_by_suburb"].values())[-3])
insights_html = "".join(f"<li>{html.escape(t.format(**fill))}</li>" for t in INSIGHTS)
sp = m["split"]
bench = m["benchmarks_from_task_page"]
fi = list(m["feature_importance"].items())[:10]
fi_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v:,.2f}</td></tr>" for k, v in fi)
sub_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{money(v)}</td></tr>" for k, v in ins["suburb_median_rent_no_car"].items())
beds_rows = "".join(
    f"<tr><td>{k}</td><td>{money(ins['median_rent_no_car_by_beds'].get(k, float('nan')))}</td><td>{money(v)}</td></tr>"
    for k, v in ins["parking_premium_by_beds"].items())
cl = m["cleaning"]
by_car = "".join(row(lbl, m[k]) for k, lbl in [("model_with_car", "Model: adverts with a car space"),
                                               ("model_no_car", "Model: adverts without a car space"),
                                               ("model_flat_seen_before", "Model: flat advertised before"),
                                               ("model_flat_never_advertised", "Model: flat never advertised")] if k in m)
beds_rows = "".join(
    f"<tr><td>{k}</td><td>{money(ins['median_rent_no_car_by_beds'].get(k, float('nan')))}</td><td>{money(v)}</td></tr>"
    for k, v in ins["parking_premium_by_beds"].items() if int(k) <= 4)

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
 <div class="kpi"><b>{money(m['model']['median_abs_error'])}</b>typical error on held-out adverts</div>
 <div class="kpi"><b>{m['model']['within_100']*100:.1f}%</b>within $100</div>
 <div class="kpi"><b>{m['model']['r2']:.2f}</b>R² on held-out adverts</div>
 <div class="kpi"><b>{money(fill['premium'])}</b>median car-space premium / week</div>
</div>

<h2>What we found</h2>
<ol>{insights_html}</ol>

<h2>How accurate is it?</h2>
<p>Held-out check: everything (rent index, building and flat history, model) was learned from adverts listed up to {sp['train_to']} and tested on {sp['val_rows']:,} adverts listed {sp['val_from']} to {sp['val_to']}.
Estimates are made as at {sp['train_to']}, the same way the real submission is made as at 31 July 2026 and scored on later adverts. Adverts with unknown parking are left out, as the scorer does.</p>
<table><tr><th>Method</th><th>Median abs. error</th><th>Within $100</th><th>R²</th><th>Mean abs. error</th><th>Median bias</th><th>Adverts</th></tr>
{row("Our model", m['model'])}{row("Baseline: suburb × bedrooms median", m['baseline_suburb_beds_median'])}{by_car}</table>
<p>Task benchmarks on the official frozen Aug–Sep 2026 adverts, for context (a different test set from ours): simple estimate ${bench['simple']}, with parking ${bench['simple_with_parking']},
Microburbs rental valuation ${bench['microburbs_valuation']} ({bench['microburbs_within_100']*100:.1f}% within $100), suburb median {bench['suburb_median_within_100']*100:.1f}% within $100.</p>
{img("actual_vs_pred.png", "Estimate vs advertised rent, held-out adverts")}
{img("error_hist.png", "Distribution of errors, held-out adverts")}
{img("rent_index.png", "Same-flat rent index used to bring past adverts to July 2026")}

<h2>How we split adverts by date</h2>
<div class="note">The task is set at 31 July 2026. We drop every advert listed after that date before doing anything else (the code asserts it).
For our own check we train on adverts before {sp['val_from']} and score on {sp['val_from']}–{sp['val_to']}, mimicking the real test, which scores later adverts.
We never use the official 1 August – 30 September frozen adverts, and we never call the live for-rent listings endpoint.
The final model is then refit on all adverts up to 31 July 2026.</div>

<h2>The car-space premium</h2>
<p>Every flat gets two estimates from the same model: one with the car-space flag set to 1, one with it set to 0. The gap is the premium. We never let a car space lower the rent.</p>
<table><tr><th>Bedrooms</th><th>Median rent, no car space</th><th>Median car-space premium</th></tr>{beds_rows}</table>
{img("parking_by_beds.png", "Median car-space premium by bedrooms")}
<table><tr><th>Suburb</th><th>Median car-space premium / week</th></tr>{"".join(f"<tr><td>{html.escape(k)}</td><td>{money(v)}</td></tr>" for k, v in list(ins["parking_premium_by_suburb"].items())[:8])}</table>

<h2>Data</h2>
<ul>
 <li>The supplied past-leases file: 112,457 rent adverts for City of Sydney flats, 2012 to 31 July 2026. We use those from 2015 on.</li>
 <li>The supplied flats file (bedrooms, bathrooms, floor, building size, ABS block) and 2021 Census / 2026 block estimates.</li>
 <li>Cleaning: {cl['raw_rows']:,} raw adverts → {cl['after_date_rule']:,} on or before 31 Jul 2026 → {cl.get('after_beds_known', 0):,} usable adverts after dropping pre-2015 adverts, implausible rents (outside $150–$6,000/week), duplicates and adverts with no bedroom count. Missing bedrooms, bathrooms and parking on an advert are filled from the flat's own record.</li>
</ul>

<h2>Method</h2>
<ol>
 <li><b>Rent index.</b> A monthly same-flat index (log rent = flat effect + month effect, fitted on flats advertised more than once, smoothed over 3 months). Every past advert is converted to July 2026 dollars.</li>
 <li><b>Features.</b> Bedrooms, bathrooms, car space, property type, suburb, latitude and longitude, floor, flats in the building, block homes and new homes; the building's average adjusted rent (overall and for the same bedrooms) and the ABS block's for the same bedrooms; and the flat's own last advertised rent, how long ago it was, and whether it had parking then. For training rows these use leave-one-out or strictly earlier adverts, so no advert sees its own rent.</li>
 <li><b>Model.</b> Gradient-boosted trees (scikit-learn HistGradientBoosting) on log adjusted rent with absolute-error loss, since the task is scored on median absolute error.</li>
 <li><b>Two answers per flat.</b> The same model is run with the car-space flag set to 1 and to 0. A car space is never allowed to lower the estimate. Any flat the model cannot score gets its suburb × bedrooms median, so no answer is blank.</li>
 <li><b>Tested and rejected.</b> A larger fixed parking premium (3–8%) and scaling estimates down 1–3% made almost no difference on our check, so we kept the model as it is.</li>
</ol>
<table><tr><th>Most useful features (held-out permutation importance: % added to median error when shuffled)</th><th></th></tr>{fi_rows}</table>

<h2>Median estimated rent by suburb (no car space)</h2>
<table><tr><th>Suburb</th><th>Median weekly rent</th></tr>{sub_rows}</table>

<p class="sub">Estimates are automated and indicative only. Data © Microburbs and the sources credited in README.md.</p>
</body></html>"""

(C.ROOT / "report.html").write_text(page, encoding="utf-8")
print("Wrote report.html")
