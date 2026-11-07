# What will this flat rent for? — Team 2more

Microburbs Hackathon, 7 November 2026, **Task 4**. Weekly asking rent for every City of Sydney flat in the supplied list, with and without a car space, as at 31 July 2026.

| Deliverable | File |
|---|---|
| Rent estimates | `rents_2more.csv` (`gnaf_id`, `rent_with_car_space`, `rent_without_car_space`) |
| Report | `report.html` |
| Pitch (≤ 45 s) | `pitch.mp4` |
| Demo (≤ 3 min) | `demo.mp4` |

**Live links:** [Report](https://hairyrambe.github.io/microburbs-2more-rents/report.html) · [Rent explorer demo (fictional flats)](https://hairyrambe.github.io/microburbs-2more-rents/rent-explorer-demo.html)

## Results
Every check re-runs the exact submission pipeline as if the date were the cut-off (history and model from earlier adverts only, input-flat records, same rounding and parking rule), then scores the later adverts.

| Held-out window | Our model (median abs. error / within $100) | Suburb × bedrooms median |
|---|---|---|
| A: built to 30 Apr 2026, tested May–Jul 2026 (3,773 adverts) | **$43.0 / 80.7%**, R² 0.91 | $100 / 56.2% |
| A, May–Jun only (2-month horizon, like the real test) | $41.0 / 81.9% | $100 / 56.9% |
| B: built to 31 Jan 2026, tested Feb–Apr 2026 (2,656 adverts) | $44.5 / 79.1% | $100 / 56.1% |

Method: a same-flat monthly rent index brings every past advert to July 2026 dollars. Gradient-boosted trees then use the past rents of the same ABS block and building (from earlier dates only), the flat's own last advert, bedrooms, bathrooms, parking, floor and location. Each flat is scored twice, with the car-space flag set to 1 and to 0. Old adverts keep their own recorded bedrooms, bathrooms and parking (never back-filled from the July input), and the model trains for a fixed 1,500 iterations on all data; both ideas came from Indra's stricter independent rebuild and improved both windows. Past-only averages beat leave-one-out averages on both windows; a bias correction did not help consistently, so none is applied. These are development checks (both windows informed choices), not official scores. Full detail and known limits are in `report.html`.

## Run it
```bash
pip install -r requirements.txt
cp .env.example .env            # paste the team key; .env is git-ignored
export MICROBURBS_API_KEY=...   # or load it from .env

# put the three supplied CSVs in data/
# optional: extra adverts from the API (to_date=2026-07-31). The submitted run used the supplied files only.
# python src/pull_rents.py all && mv rent_adverts.csv data/

python src/build_model.py --inspect   # check column mapping (fix in src/config.py if needed)
python src/build_model.py             # validate, fit, write rents_2more.csv
python src/build_report.py            # write report.html
```
`src/build_model.py` runs all validation windows, the encoding comparison and the calibration grid itself. `tools/` holds earlier exploratory checks (fixed parking premium, ensembles, raw within-building parking difference). `tools/make_fake_data.py` makes synthetic data to test the code (`MB_DATA=fake_data python src/build_model.py`). It was never used for the submitted estimates.

## Rent explorer app (local)
**Easiest:** open `rent-explorer-demo.html` (fictional flats, safe to share). `python tools/build_standalone.py` builds the full single-file version with all 65,777 flats from the supplied data; it is git-ignored because it contains supplied addresses.

A local web app to look up any flat's estimate with and without parking (design and app code by Indra; wired to this repo's model).
- Put the supplied `rents-input-flats-city-of-sydney.csv` in `data/` (git-ignored; never committed).
- Mac: double-click `START_RENT_APP.command` (or run `python3 rent_app.py`). Windows: `START_RENT_APP.cmd`. It opens http://127.0.0.1:8765.
- No data? `START_DEMO_APP.command` / `.cmd` shows four fictional flats, safe for public recordings.
- The accuracy panel only appears when `rents_2more.csv` matches the fingerprint in `history_manifest.json`, written by `src/build_model.py`. Tests: `python3 -m unittest test_rent_app`.

## Date rule
Nothing dated after 31 July 2026 is used. API adverts are requested with `to_date=2026-07-31`, and the model drops and asserts against any later advert. We never use the live `listings/for-rent` endpoint or the official Aug–Sep frozen adverts.

## Not in this repo (by the rules)
No API key, no supplied files, and no API output. `data/`, `raw/` and `.env` are git-ignored.

## Sources and credits
- **Microburbs Hackathon API** (`api-ht.microburbs.com.au`): API docs and the optional advert downloader. The submitted estimates use only the supplied files. Data © Microburbs, used under the hackathon terms.
- **Supplied hackathon files** (`rents-input-flats-city-of-sydney.csv`, `rents-past-leases-city-of-sydney.csv`, `blocks-homes-and-people-2021-2026.csv`): Microburbs, used on the day only and not republished.
- **ABS 2021 Census** mesh-block counts (via the supplied blocks file). © Commonwealth of Australia, CC BY 4.0.
- **G-NAF** address identifiers. © Geoscape Australia, under the G-NAF End User Licence Agreement.
- API client pattern adapted from [microburbs-hackathon-demos](https://github.com/Microburbs/microburbs-hackathon-demos) (MIT).
- Libraries: pandas, NumPy, scikit-learn, matplotlib, requests.
- No other external data, images or live listings were used to build the estimates. The explorer's "Find listings" links only open a web search for the address.

## Team
- **Noel Koh**: modelling pipeline, validation and report.
- **Indra**: rent explorer app, and an independent stricter rebuild of the model that cross-checked ours on the same adverts (within $1); two of its changes are adopted here.
- **Alden Bay**: pitch and demo.
