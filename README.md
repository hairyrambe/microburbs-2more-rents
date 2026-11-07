# What will this flat rent for? — Team 2more

Microburbs Hackathon, 7 November 2026, **Task 4**. Weekly asking rent for every City of Sydney flat in the supplied list, with and without a car space, as at 31 July 2026.

| Deliverable | File |
|---|---|
| Rent estimates | `rents_2more.csv` (`gnaf_id`, `rent_with_car_space`, `rent_without_car_space`) |
| Report | `report.html` |
| Pitch (≤ 45 s) | `pitch.mp4` |
| Demo (≤ 3 min) | `demo.mp4` |

## Results
Held-out check: built only from adverts up to 30 April 2026, tested on 3,964 adverts from 1 May to 31 July 2026.

| | Median abs. error | Within $100 | R² |
|---|---|---|---|
| **Our model** | **$45** | **79.6%** | **0.90** |
| Suburb × bedrooms median | $100 | 55.5% | 0.61 |

Method: a same-flat monthly rent index brings every past advert to July 2026 dollars. Then gradient-boosted trees use the flat's own rent history, the building's and ABS block's past rents, bedrooms, bathrooms, parking, floor and location. Each flat is scored twice, with the car-space flag set to 1 and to 0. Full detail in `report.html`.

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
`tools/val_experiments.py` re-runs the held-out checks of a fixed parking premium and a scaling adjustment, both of which we rejected. `tools/analyse.py` measures the raw within-building parking premium. `tools/make_fake_data.py` makes synthetic data to test the code (`MB_DATA=fake_data python src/build_model.py`). It was never used for the submitted estimates.

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
- TODO: add any other open data used (e.g. OpenStreetMap © OpenStreetMap contributors, ODbL).

## Team
Noel Koh, Alden Bay, Indrapa Hewakaluge.
