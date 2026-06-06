# Vera

The truth about what's in your food.

Search any food product and get a score — but unlike opaque apps that hand you a single number with no explanation, Vera breaks down exactly *why* a product scores the way it does, shows the evidence behind every flagged ingredient, and tells you how confident it is in the data.

---

## Why not just use Yuka?

Yuka is popular, but it has well-documented flaws:

| Yuka | Vera |
|------|------|
| Single verdict, no breakdown | Three visible dimensions, each scored separately |
| Opaque weighting | Weights shown as percentages — and you can change them |
| Flags additives with no evidence | Every flagged additive shows the science, dose/context, and a source link |
| No data quality signal | Confidence badge (High / Medium / Low) with reasons |
| No link to the source data | Direct link to the Open Food Facts product page |
| Implies false precision | Acknowledges uncertainty explicitly |

---

## How scoring works

Every product is scored across three dimensions. Each dimension is scored 0–100 and the final score is their weighted sum.

### 1. Nutritional Quality (default 50%)
Derived directly from the product's **Nutri-Score grade** (A–E), mapped to a 0–100 scale. The mapping is a deliberate v1 simplification — it's documented and easy to find in [`app/scoring/tables.py`](app/scoring/tables.py).

| Nutri-Score | Score |
|-------------|-------|
| A | 100 |
| B | 80 |
| C | 60 |
| D | 40 |
| E | 20 |

### 2. Additives (default 30%)
Each E-number in the product is looked up in a hybrid database — a baseline of ~40 common additives from the Open Food Facts taxonomy, enriched with a hand-curated set of 20 entries that include evidence summaries, dose/context notes, and source links (primarily EFSA opinions and peer-reviewed studies).

High-risk additives deduct 30 points each; moderate-risk deduct 10. Every flag is shown as a collapsible evidence card so you can read the reasoning rather than just accept the verdict.

### 3. Processing Level (default 20%)
Derived from the product's **NOVA group** (1–4), which classifies how industrially processed a food is.

| NOVA group | Score |
|------------|-------|
| 1 — Unprocessed | 100 |
| 2 — Culinary ingredients | 75 |
| 3 — Processed foods | 40 |
| 4 — Ultra-processed | 0 |

### Adjustable weights

The three default weights (50 / 30 / 20) are shown on the score page as sliders. Drag any slider and the overall score recalculates instantly — no page reload. If you care more about additives than nutrition, set it that way. The app doesn't decide your priorities for you.

### Data confidence

If Open Food Facts is missing Nutri-Score or NOVA data for a product, the confidence badge drops from High to Medium or Low, with a plain-English explanation of what's missing. The score is still shown, but you know how much to trust it.

---

## Tech stack

- **Backend:** Python 3.12, FastAPI
- **Templates:** Jinja2 (server-rendered HTML — the score page works without JavaScript)
- **Frontend:** Vanilla JS (~100 lines), no framework, no build step
- **Data:** [Open Food Facts](https://world.openfoodfacts.org/) API (search by product name)
- **Styling:** Hand-written CSS, no framework
- **Deployment:** Docker / docker-compose

The scoring engine is a pluggable Python `Protocol`. Adding a cosmetics scorer later requires only a new engine class — no changes to the routes, templates, or JS.

---

## Running locally

**Prerequisites:** Python 3.12+

```bash
# 1. Clone and enter the project
git clone https://github.com/Churmann/Vera.git
cd Vera

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
uvicorn app.main:app --port 8000
```

Open `http://localhost:8000` in your browser and search for any food product by name.

**With Docker:**

```bash
docker-compose up
```

The app will be available at `http://localhost:8000`.

**Configuration** (all optional — defaults work out of the box):

Copy `.env.example` to `.env` and edit as needed:

```
OFF_USER_AGENT=VeraApp/1.0 (your@email.com)
OFF_REQUEST_TIMEOUT=8
DEFAULT_WEIGHT_NUTRITION=0.5
DEFAULT_WEIGHT_ADDITIVES=0.3
DEFAULT_WEIGHT_NOVA=0.2
```

---

## Running the tests

```bash
pytest
```

165 tests covering the scoring engine, additives database, Open Food Facts client, and all routes.

---

## Data sources and licence

Product data is fetched from [Open Food Facts](https://world.openfoodfacts.org/), which is made available under the [Open Database Licence (ODbL)](https://opendatacommons.org/licenses/odbl/). Individual contents are available under the [Database Contents Licence (DbCL)](https://opendatacommons.org/licenses/dbcl/).

Additive evidence summaries are drawn from EFSA opinions, IARC monographs, and peer-reviewed literature. Source links are shown on each evidence card.

Scores are informational only and are not medical or dietary advice.
