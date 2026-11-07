"""Build ONE self-contained HTML file of the rent explorer (Indra's app design) with every flat built in.

    python tools/build_standalone.py            # real data  -> rent-explorer-LOCAL-ONLY.html (never publish)
    python tools/build_standalone.py --demo     # fictional  -> rent-explorer-demo.html (safe to share)

Anyone can double-click the output to open it in a browser: no Python, server or launcher needed.
The /api calls of app_ui/app.js are replaced by the same logic running in the page.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import rent_app  # noqa: E402

LOCAL_API = r"""
const FIELDS = ['gnaf_id','address','suburb','bedrooms','bathrooms','floor_level','car_space','with_parking','without_parking'];
const ROWS = __ROWS__.map(r => Object.fromEntries(FIELDS.map((f, i) => [f, r[i]])));
const META = __META__;
const INDEX = new Map(ROWS.map(r => [r.gnaf_id, r]));
const natural = t => t.split(/(\d+)/).map(p => /^\d+$/.test(p) ? [0, +p] : [1, p.toLowerCase()]);
function cmpNat(a, b) {
  const x = natural(a), y = natural(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    if (x[i][0] !== y[i][0]) return x[i][0] - y[i][0];
    if (x[i][1] < y[i][1]) return -1; if (x[i][1] > y[i][1]) return 1;
  }
  return x.length - y.length;
}
const ORDERED = ROWS.slice().sort((a, b) => a.suburb < b.suburb ? -1 : a.suburb > b.suburb ? 1 : cmpNat(a.address, b.address));
const KEYS = new Map(ROWS.map(r => [r.gnaf_id, `${r.address} ${r.suburb} ${r.gnaf_id}`.toLowerCase()]));
function searchRows(q) {
  const tokens = (q.get('q') || '').toLowerCase().split(/\s+/).filter(Boolean);
  const suburb = q.get('suburb') || '', beds = q.get('beds') || '';
  let page = Math.max(1, parseInt(q.get('page') || '1', 10) || 1);
  const matches = [];
  for (const r of ORDERED) {
    if (suburb && r.suburb !== suburb) continue;
    if (beds) {
      if (r.bedrooms == null) continue;
      if (beds === '3+') { if (r.bedrooms < 3) continue; } else if (r.bedrooms !== +beds) continue;
    }
    const k = KEYS.get(r.gnaf_id);
    if (tokens.every(t => k.includes(t))) matches.push(r);
  }
  const size = 20, pages = Math.max(1, Math.ceil(matches.length / size));
  page = Math.min(page, pages);
  const start = (page - 1) * size;
  return { total: matches.length, page, pages, start: matches.length ? start + 1 : 0,
           end: Math.min(start + size, matches.length),
           items: matches.slice(start, start + size).map(r => ({ gnaf_id: r.gnaf_id, address: r.address, suburb: r.suburb, bedrooms: r.bedrooms, bathrooms: r.bathrooms })) };
}
async function api(path) {
  const url = new URL(path, 'https://local.invalid');
  if (url.pathname === '/api/meta') return META;
  if (url.pathname === '/api/search') return searchRows(url.searchParams);
  if (url.pathname === '/api/property') {
    const r = INDEX.get(url.searchParams.get('id') || '');
    if (!r) throw Error('Flat not found');
    return r;
  }
  throw Error('Not found');
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    rows, source, demo = rent_app.load_data(root=ROOT, demo=args.demo)
    metrics = rent_app.verified_metrics(ROOT, "rents_2more.csv", demo=args.demo)
    fields = ["gnaf_id", "address", "suburb", "bedrooms", "bathrooms", "floor_level", "car_space", "with_parking", "without_parking"]
    compact = [[r[f] for f in fields] for r in rows]
    meta = dict(count=len(rows), suburbs=sorted({r["suburb"] for r in rows}), source=source, demo=demo,
                metrics=metrics, report_available=True)

    ui = ROOT / "app_ui"
    js = (ui / "app.js").read_text(encoding="utf-8")
    start = js.index("async function api(path) {")
    end = js.index("}\n", start) + 2
    js = js[:start] + LOCAL_API.replace("__ROWS__", json.dumps(compact, separators=(",", ":"))).replace(
        "__META__", json.dumps(meta)) + js[end:]
    css = (ui / "styles.css").read_text(encoding="utf-8")
    page = (ui / "index.html").read_text(encoding="utf-8")
    page = page.replace('<link rel="stylesheet" href="/styles.css">', f"<style>{css}</style>")
    page = page.replace('<script src="/app.js" defer></script>', "")
    page = page.replace('href="/report"', 'href="report.html"').replace('class="brand" href="/"', 'class="brand" href="#"')
    if not demo:
        page = page.replace("Local explorer · No data uploads", "Single-file explorer · Contains supplied data, do not publish")
    page = page.replace("</body></html>", f"<script>{js}</script></body></html>")
    out = ROOT / ("rent-explorer-demo.html" if demo else "rent-explorer-LOCAL-ONLY.html")
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out.name} ({out.stat().st_size / 1e6:.1f} MB, {len(rows):,} flats)")


if __name__ == "__main__":
    main()
