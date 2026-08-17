# APSN Big Ten Weekly

One scrollable page per week: every Big Ten matchup, every prediction
model's number and every sportsbook line shown side by side (never
averaged), plus a hand-written summary per game. Static HTML, rebuilt on a
schedule, deployed to GitHub Pages.

Not a consensus engine, not an ML project, not a betting product. See the
build brief this repo was built from for the full rationale.

## Stack

Python 3.11+, Postgres (Supabase free tier), Jinja2 → static HTML, GitHub
Actions for scheduling + deploy, GitHub Pages for hosting. No frontend
framework.

## One-time setup

1. **CFBD API key.** Register at collegefootballdata.com with a `.edu`
   email for the free academic tier (3,000 calls/month). This project uses
   well under 50 calls per weekly collection.
2. **Supabase project.** Create a free-tier project, grab the Postgres
   connection string (Project Settings → Database → Connection string,
   "URI" format) as `DATABASE_URL`.
3. **Local env:**
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # fill in CFBD_API_KEY and DATABASE_URL
   ```
4. **Apply the schema:** `python migrate.py`

## Running it locally

```
python collect.py                # auto-detects current season/week
python collect.py --year 2026 --week 1   # explicit, for backfill/testing

python build.py                  # builds the current week
python build.py --all-weeks      # rebuilds every week in the DB

python -m http.server --directory site 8000   # preview at localhost:8000
```

Both scripts are safe to re-run. `collect.py` only ever inserts new
`predictions`/`odds_snapshots` rows (append-only, by design -- see
`conversions.py`'s module docstring) and upserts `teams`/`games`.

## Before trusting the numbers: verify the spread sign convention

`conversions.py` assumes CFBD's `/lines` `spread` field is home-team
perspective (negative = home favored). That assumption was written without
a live API key and is **not yet empirically confirmed** -- see the warning
at the top of `conversions.py`. Once `CFBD_API_KEY` is set:

```
pytest tests/test_spread_sign_convention.py -v
```

This pulls real lines data and self-checks the sign against moneyline sign
(unambiguous in American odds), rather than relying on a hardcoded game. It
must pass before the site's model-vs-market comparisons can be trusted. It
runs automatically in CI once `CFBD_API_KEY` is added as a repo secret.

## Tests

```
pytest tests/ -v
```

50 tests cover the conversion math (both spread signs, neutral-site HFA,
de-vigged moneylines summing to 1.0), the collector's failure isolation
(one broken source doesn't abort the run), and the generator's data shaping
(sorting, divergence chips, em-dash fallback for missing models, draft
summaries never rendering) -- all against mocked CFBD responses and a fake
DB connection, since no live credentials were available while building
this. Everything here ran and passed locally; nothing was hand-waved.

## Deploying

1. Push this repo to GitHub.
2. Add repo secrets: Settings → Secrets and variables → Actions →
   `CFBD_API_KEY`, `DATABASE_URL`.
3. Enable Pages: Settings → Pages → Source: **GitHub Actions**.
4. `.github/workflows/deploy.yml` runs on a schedule (Tue/Thu/Sat mornings,
   12:00 UTC -- see the file for why cadence matters here: line movement
   between snapshots is the one part of the record that can't be
   backfilled) and on every push to `main`, so editing a summary or the CSS
   redeploys without waiting for the next scheduled collection.
5. `.github/workflows/test.yml` runs the test suite on every push/PR.

## Writing summaries

Markdown files, not database rows -- see `content/summaries/README.md` for
the format and the rules the build enforces (`status: draft` never
renders; `generated_by: llm` gets a visible AI-generated label).

## Submission form

`templates/week.html` has a Formspree form with a placeholder
`action="https://formspree.io/f/YOUR_FORM_ID"`. Create a free form at
formspree.io and replace `YOUR_FORM_ID` before launch, or it will 404 on
submit.

## Project layout

```
conversions.py       all prediction/odds arithmetic, nowhere else does math
cfbd_client.py        thin CFBD API wrapper, verified against the live OpenAPI spec
collect.py             weekly collector, one source's failure never blocks the rest
build.py                reads Postgres + content/summaries/, writes site/
config.py, db.py, migrate.py    env, connection, schema application
db/migrations/         append-only numbered SQL migrations
templates/              Jinja2 templates
assets/                  CSS, JS, logo, favicon
content/summaries/      hand-written per-game markdown
summarize/generate.py   LLM summary seam, NotImplementedError in v1
tests/                   50 tests, see "Tests" above
.github/workflows/      deploy.yml (collect+build+deploy), test.yml (CI)
```

## What's still manual before Week 1

- [ ] Get a real `CFBD_API_KEY` and confirm the spread sign convention test
      passes (see above) -- this is the one thing that can silently invert
      the whole site if skipped.
- [ ] Create the Supabase project and set `DATABASE_URL`.
- [ ] Push to GitHub, add both secrets, enable Pages (Actions source).
- [ ] Create a Formspree form and swap in the real ID.
- [ ] Write summaries for as many Week 1 games as time allows (optional --
      a missing summary renders cleanly).
