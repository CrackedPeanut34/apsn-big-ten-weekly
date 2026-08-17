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

## Spread sign convention

`conversions.py` assumes CFBD's `/lines` `spread` field is home-team
perspective (negative = home favored). **Confirmed against live data** by
`tests/test_spread_sign_convention.py`, which cross-checks spread sign
against moneyline sign (unambiguous in American odds) rather than relying
on a hardcoded game. It runs automatically in CI now that `CFBD_API_KEY` is
a repo secret -- if CFBD ever changes this behavior, that test is what
catches it.

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

`templates/week.html` posts to a Formspree form (`formspree.io/f/mkjwqjqe`).
Submissions show up in the Formspree dashboard under that account -- there's
no database table wired up on purpose (see build brief section 10).

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

## Status

Live at https://crackedpeanut34.github.io/apsn-big-ten-weekly/. CFBD key,
Supabase DB, GitHub secrets, Pages, and the Formspree form are all wired up
and confirmed working against real 2026 Week 1 data.

Two things worth knowing, found while wiring this up for real:

- Supabase's **direct** connection string (`db.<ref>.supabase.co`) resolves
  to an IPv6-only address. That works from a machine with IPv6 (most home
  ISPs) but not from GitHub Actions runners (`Network is unreachable`).
  `DATABASE_URL` uses the **session pooler** string
  (`aws-0-<region>.pooler.supabase.com:5432`, username
  `postgres.<project-ref>`) instead, which supports IPv4 and works in both
  places. If `DATABASE_URL` ever gets regenerated from Supabase, grab the
  pooler variant, not the direct one.
- Team refresh and the SRS/Elo/FPI rating pulls are intentionally *not*
  filtered to `conference=B1G`. Nonconference opponents (FCS cupcakes,
  other-conference teams) need a team row and a rating too, or the
  home-minus-away margin calc has nothing to subtract and that model's row
  silently em-dashes for every nonconference game. Only `/games`,
  `/games/media`, and `/lines` stay conference-filtered, since those are
  fetched per-game rather than per-team.

Remaining, whenever there's time (none of it blocks the site working):
- [ ] Write summaries for Week 1 games (optional -- a missing summary
      renders cleanly, and it's ~9-18 files of manual writing either way).
- [ ] Consider resetting the Supabase DB password, since it was pasted in
      this chat session.
