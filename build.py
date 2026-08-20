"""Static site generator. Reads Postgres + content/summaries/*.md, writes
site/. No network calls, no API keys -- everything here is static once
collect.py has run.

Usage:
    python build.py                        # auto-detect current season/week
    python build.py --year 2026 --week 1    # explicit
    python build.py --all-weeks             # rebuild every week found in the DB
"""
import argparse
import datetime as dt
import os
import pathlib
import shutil
import sys
from zoneinfo import ZoneInfo

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
import markdown as md

import db

ROOT = pathlib.Path(__file__).parent
SITE_DIR = ROOT / "site"
TEMPLATES_DIR = ROOT / "templates"
SUMMARIES_DIR = ROOT / "content" / "summaries"
ASSETS_DIR = ROOT / "assets"

DIVERGENCE_THRESHOLD = 3.0       # points
EASTERN = ZoneInfo("America/New_York")

# Display order for sportsbook rows. CFBD's /lines only covers Bovada and
# DraftKings for these games today -- FanDuel is listed so it slots into
# place automatically if CFBD adds coverage later. Unlisted providers sort
# after these, alphabetically among themselves.
PROVIDER_ORDER = {"DraftKings": 0, "FanDuel": 1, "Bovada": 2}

# Who makes each model, what it's built from, and how it differs from the
# others -- keyed by model_sources.slug. Separate from model_sources.notes,
# which stays focused on this project's own conversion caveats (e.g. HFA).
GLOSSARY_DESCRIPTIONS = {
    "sp-plus": (
        "Built by Bill Connelly, a college football analyst at ESPN (he "
        "created it in 2008 at Football Outsiders, before joining ESPN in "
        "2019). It's a tempo- and opponent-adjusted efficiency rating "
        "pulled from play-by-play data -- success rate and explosiveness "
        "on a per-play basis -- rather than just final scores. It's meant "
        "to predict how a team will play going forward, not to reward past "
        "results."
    ),
    "srs": (
        "Simple Rating System, originally devised by Doug Drinen at "
        "Pro-Football-Reference; CollegeFootballData runs the college "
        "football version. It's the simplest model on this page: a system "
        "of equations solved so each team's rating equals its average "
        "scoring margin, adjusted for opponents' ratings. No play-by-play "
        "or efficiency data, just final scores."
    ),
    "elo": (
        "Adapted from the rating system physicist Arpad Elo devised for "
        "chess; CollegeFootballData runs the college football version. "
        "Unlike the others here, it isn't recalculated fresh each week -- "
        "it's a running rating that shifts after every game based on the "
        "result and the pre-game rating gap, carrying over between seasons "
        "with some regression toward the mean."
    ),
    "fpi": (
        "ESPN's Football Power Index -- built independently of SP+ despite "
        "both being ESPN products. Combines separately modeled offense, "
        "defense, and special-teams components grounded in EPA (expected "
        "points added) with preseason inputs like returning production, "
        "recruiting, and coaching tenure, then simulates the rest of the "
        "season thousands of times."
    ),
    "cfbd-pregame-wp": (
        "CollegeFootballData's own machine learning model (gradient-"
        "boosted trees via XGBoost), trained directly on historical game "
        "outcomes using features like team ratings, rankings, recruiting, "
        "and home/neutral-site status. It's the only source here whose "
        "native output is already a win probability -- this page's margin "
        "column is back-derived from it, not the other way around."
    ),
}

# Elo ratings are large integers (~1200-2200); everything else on the
# rankings page is a small points-above-average number best shown to one
# decimal. Keyed by model_sources.slug, default "{:.1f}" if unlisted.
RATING_FORMATS = {"elo": "{:.0f}"}


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def week_filename(week: int, season_type: str) -> str:
    """Regular-season URLs stay exactly as they've always been
    (week-01.html); postseason weeks get a distinguishing prefix so a
    postseason week 1 (bowls restart week numbering from 1, same as the
    regular season does) can never collide with -- and silently overwrite
    -- the real regular-season week 1 page."""
    prefix = "" if season_type == "regular" else f"{season_type}-"
    return f"{prefix}week-{week:02d}.html"


def rankings_filename(week: int, season_type: str) -> str:
    prefix = "" if season_type == "regular" else f"{season_type}-"
    return f"{prefix}rankings-week-{week:02d}.html"


# --- DB reads ----------------------------------------------------------------

def determine_default_week(conn) -> tuple[int, int, str]:
    """Picks the most relevant (season, week, season_type) already in the
    DB: the most-recently-started week that has kicked off, or if the
    season hasn't started yet, the earliest upcoming week. Compares by
    actual kickoff date rather than week number, since postseason week
    numbers restart from 1 and would otherwise look "earlier" than a late
    regular-season week."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT season, week, season_type, min(start_date) AS week_start
            FROM games
            GROUP BY season, week, season_type
            """
        )
        rows = cur.fetchall()

    if not rows:
        raise RuntimeError("no games in the database -- run collect.py first")

    latest_season = max(r["season"] for r in rows)
    season_rows = [r for r in rows if r["season"] == latest_season]
    now = dt.datetime.now(dt.timezone.utc)

    past_or_current = [r for r in season_rows if r["week_start"] and r["week_start"] <= now]
    if past_or_current:
        chosen = max(past_or_current, key=lambda r: r["week_start"])
    else:
        upcoming = [r for r in season_rows if r["week_start"]]
        chosen = min(upcoming, key=lambda r: r["week_start"]) if upcoming else season_rows[0]
    return chosen["season"], chosen["week"], chosen["season_type"]


def list_all_weeks(conn) -> list[tuple[int, int, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT season, week, season_type, (season_type = 'postseason') AS is_postseason
            FROM games
            ORDER BY season, is_postseason, week
            """
        )
        return [(r["season"], r["week"], r["season_type"]) for r in cur.fetchall()]


def fetch_week_games(conn, season: int, week: int, season_type: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.*,
                   ht.school AS home_school, ht.abbreviation AS home_abbr,
                   ht.logo_url AS home_logo_url, ht.logo_dark_url AS home_logo_dark_url,
                   ht.color AS home_color, ht.alt_color AS home_alt_color,
                   ht.conference AS home_conference,
                   at.school AS away_school, at.abbreviation AS away_abbr,
                   at.logo_url AS away_logo_url, at.logo_dark_url AS away_logo_dark_url,
                   at.color AS away_color, at.alt_color AS away_alt_color,
                   at.conference AS away_conference
            FROM games g
            JOIN teams ht ON ht.id = g.home_team_id
            JOIN teams at ON at.id = g.away_team_id
            WHERE g.season = %(season)s AND g.week = %(week)s AND g.season_type = %(season_type)s
            ORDER BY g.start_date
            """,
            {"season": season, "week": week, "season_type": season_type},
        )
        return cur.fetchall()


def fetch_latest_predictions(conn, game_ids: list[int]) -> dict[int, list[dict]]:
    """Latest predictions row per (game_id, model_source_id), for every
    active model source -- including sources with no row for that game, so
    missing coverage can render as an em dash rather than being silently
    dropped."""
    if not game_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM model_sources WHERE active = TRUE ORDER BY id"
        )
        sources = cur.fetchall()

        cur.execute(
            """
            SELECT DISTINCT ON (p.game_id, p.model_source_id)
                   p.*
            FROM predictions p
            WHERE p.game_id = ANY(%(game_ids)s)
            ORDER BY p.game_id, p.model_source_id, p.collected_at DESC
            """,
            {"game_ids": game_ids},
        )
        latest = cur.fetchall()

    by_game_and_source = {(p["game_id"], p["model_source_id"]): p for p in latest}
    result: dict[int, list[dict]] = {gid: [] for gid in game_ids}
    for gid in game_ids:
        for source in sources:
            pred = by_game_and_source.get((gid, source["id"]))
            result[gid].append({"source": source, "prediction": pred})
    return result


def fetch_latest_odds(conn, game_ids: list[int]) -> dict[int, list[dict]]:
    if not game_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (o.game_id, o.provider)
                   o.*
            FROM odds_snapshots o
            WHERE o.game_id = ANY(%(game_ids)s)
            ORDER BY o.game_id, o.provider, o.collected_at DESC
            """,
            {"game_ids": game_ids},
        )
        rows = cur.fetchall()

    result: dict[int, list[dict]] = {gid: [] for gid in game_ids}
    for row in rows:
        result[row["game_id"]].append(row)
    return result


def fetch_team_records(conn, season: int) -> dict[int, tuple[int, int]]:
    """Wins/losses per Big Ten team, straight from games already collected --
    no new data source. Counts every played game (home_points/away_points
    both set), conference or not, so it updates on its own as collect.py
    picks up new results week over week; nothing to maintain by hand."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                t.id AS team_id,
                COUNT(*) FILTER (
                    WHERE (g.home_team_id = t.id AND g.home_points > g.away_points)
                       OR (g.away_team_id = t.id AND g.away_points > g.home_points)
                ) AS wins,
                COUNT(*) FILTER (
                    WHERE (g.home_team_id = t.id AND g.home_points < g.away_points)
                       OR (g.away_team_id = t.id AND g.away_points < g.home_points)
                ) AS losses
            FROM teams t
            LEFT JOIN games g
                ON (g.home_team_id = t.id OR g.away_team_id = t.id)
                AND g.season = %(season)s
                AND g.home_points IS NOT NULL AND g.away_points IS NOT NULL
            WHERE t.conference = 'Big Ten'
            GROUP BY t.id
            """,
            {"season": season},
        )
        return {row["team_id"]: (row["wins"], row["losses"]) for row in cur.fetchall()}


def compute_national_ranks(latest: list[dict]) -> dict[tuple[int, int], int]:
    """Rank every team a source has a rating for (all FBS, not just Big
    Ten) against each other, per source. Ties share a rank (1, 2, 2, 4...),
    same convention AP/Coaches polls use. Keyed by (team_id, model_source_id)."""
    by_source: dict[int, list[tuple[int, float]]] = {}
    for r in latest:
        by_source.setdefault(r["model_source_id"], []).append(
            (r["team_id"], float(r["raw_value"]))
        )

    national_rank: dict[tuple[int, int], int] = {}
    for source_id, team_values in by_source.items():
        team_values.sort(key=lambda tv: tv[1], reverse=True)
        prev_value, prev_rank = None, 0
        for i, (team_id, value) in enumerate(team_values, start=1):
            rank = i if value != prev_value else prev_rank
            national_rank[(team_id, source_id)] = rank
            prev_value, prev_rank = value, rank
    return national_rank


def fetch_ap_ranks(conn, season: int, week: int, season_type: str) -> dict[int, int]:
    """team_id -> AP Top 25 rank, as of this week specifically -- same week-
    and season_type-pinning as team_ratings (0004_week_scoped_rankings.sql,
    0005_season_type_scoped_ratings.sql), so a team's rank here never
    changes once a later week's poll has its own rows -- including a
    postseason week reusing a regular-season week number. Shared by the
    rankings table and by game cards (rank badge next to each team's
    logo), so there's exactly one query for "this week's AP rank."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (pr.team_id)
                   pr.team_id, pr.poll_rank
            FROM poll_rankings pr
            WHERE pr.season = %(season)s AND pr.week = %(week)s
              AND pr.season_type = %(season_type)s AND pr.poll = %(poll)s
            ORDER BY pr.team_id, pr.collected_at DESC
            """,
            {"season": season, "week": week, "season_type": season_type, "poll": "AP Top 25"},
        )
        return {row["team_id"]: row["poll_rank"] for row in cur.fetchall()}


def fetch_team_ratings(conn, season: int, week: int, season_type: str) -> tuple[list[dict], list[dict]]:
    """Every Big Ten team's rating from every active power-rating source, as
    of one specific week -- pinned there forever by week and season_type
    (0004_week_scoped_rankings.sql, 0005_season_type_scoped_ratings.sql),
    same as a game's odds/predictions never drift once collected. CFBD
    Pregame Win Probability is excluded -- it isn't a standalone team
    rating, it's a per-game output (see build_game_card's model_rows for
    that one instead)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM model_sources WHERE active = TRUE AND output_type = 'power_rating' ORDER BY id"
        )
        sources = cur.fetchall()

        cur.execute(
            "SELECT id, school, logo_url FROM teams WHERE conference = 'Big Ten' ORDER BY school"
        )
        big_ten_teams = cur.fetchall()

        # Latest row per (team, source) as of this week specifically -- not
        # "latest ever", so this never changes once a later week exists.
        # Deliberately not conference-filtered: national rank needs every
        # FBS team's rating, not just Big Ten's.
        cur.execute(
            """
            SELECT DISTINCT ON (tr.team_id, tr.model_source_id)
                   tr.*
            FROM team_ratings tr
            WHERE tr.season = %(season)s AND tr.week = %(week)s AND tr.season_type = %(season_type)s
            ORDER BY tr.team_id, tr.model_source_id, tr.collected_at DESC
            """,
            {"season": season, "week": week, "season_type": season_type},
        )
        latest = cur.fetchall()

    ap_rank_by_team = fetch_ap_ranks(conn, season, week, season_type)
    national_rank = compute_national_ranks(latest)
    records = fetch_team_records(conn, season)
    by_team_and_source = {(r["team_id"], r["model_source_id"]): r for r in latest}
    rows = []
    for team in big_ten_teams:
        wins, losses = records.get(team["id"], (0, 0))
        cells = []
        for source in sources:
            r = by_team_and_source.get((team["id"], source["id"]))
            value = float(r["raw_value"]) if r and r["raw_value"] is not None else None
            fmt = RATING_FORMATS.get(source["slug"], "{:.1f}")
            cells.append({
                "slug": source["slug"],
                "value": value,
                "display": fmt.format(value) if value is not None else "—",
                "national_rank": national_rank.get((team["id"], source["id"])),
            })
        rows.append({
            "school": team["school"],
            "logo_url": team["logo_url"],
            "record_display": f"{wins}-{losses}",
            "record_value": wins / (wins + losses) if (wins + losses) > 0 else None,
            "ap_rank": ap_rank_by_team.get(team["id"]),
            "cells": cells,
        })
    return rows, sources


# --- pure data shaping (no DB, no I/O -- unit testable) -----------------------

def market_avg_margin(odds_rows: list[dict]) -> float | None:
    values = [float(o["margin_home"]) for o in odds_rows if o.get("margin_home") is not None]
    if not values:
        return None
    return sum(values) / len(values)


def divergence_chip(model_margin_home: float | None, market_margin: float | None) -> float | None:
    """Returns the signed point gap if it's >= threshold, else None (no chip).
    Always in points -- never percentage points, per the brief."""
    if model_margin_home is None or market_margin is None:
        return None
    gap = model_margin_home - market_margin
    if abs(gap) < DIVERGENCE_THRESHOLD:
        return None
    return gap


def market_closeness_key(odds_rows: list[dict]) -> float:
    """Sort key for 'tightest spread at top'. Games with no market data sort
    last (least tight -- we can't claim closeness we don't have)."""
    values = [abs(float(o["margin_home"])) for o in odds_rows if o.get("margin_home") is not None]
    if not values:
        return float("inf")
    return min(values)


def em_dash_if_none(value, fmt: str = "{:.1f}") -> str:
    if value is None:
        return "—"
    return fmt.format(float(value))


def win_prob_pct_display(win_prob_home: float | None) -> str:
    """win_prob_home -> rounded percentage, capped at 99% -- a model/book
    saying "100%" reads as certainty nothing here actually claims."""
    if win_prob_home is None:
        return "—"
    return f"{min(round(win_prob_home * 100), 99)}%"


def extract_fpi(predictions: list[dict]) -> tuple[float, float] | None:
    """Each team's own FPI rating for this game, read back out of the FPI
    model's raw_payload (raw_value on that row is home - away, not useful
    here). None if this game has no FPI coverage (e.g. an FCS opponent)."""
    for entry in predictions:
        if entry["source"]["slug"] == "fpi" and entry["prediction"] is not None:
            payload = entry["prediction"]["raw_payload"]
            return float(payload["home"]["fpi"]), float(payload["away"]["fpi"])
    return None


def eastern_kickoff(value) -> str:
    if value is None:
        return "TBD"
    return value.astimezone(EASTERN).strftime("%a %-m/%-d %-I:%M %p ET")


def parse_summary(game_id: int, season: int, week: int) -> dict | None:
    """Reads content/summaries/{season}/week-{week:02d}/{game_id}.md. Returns
    None if the file is missing (card renders without a summary block, no
    error) or if status != 'published'."""
    path = SUMMARIES_DIR / str(season) / f"week-{week:02d}" / f"{game_id}.md"
    if not path.exists():
        return None

    text = path.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()

    status = frontmatter.get("status", "draft")
    if status != "published":
        return None

    return {
        "author": frontmatter.get("author"),
        "sources": frontmatter.get("sources", []),
        "generated_by": frontmatter.get("generated_by", "human"),
        "status": status,
        "html": md.markdown(body),
    }


# --- assembly ------------------------------------------------------------

def favored_team_abbr(margin_home: float | None, game: dict) -> str | None:
    if margin_home is None or margin_home == 0:
        return None
    return game["home_abbr"] if margin_home > 0 else game["away_abbr"]


def game_winner(home_points: int | None, away_points: int | None) -> str | None:
    """'home', 'away', or None if unplayed (or, in principle, tied)."""
    if home_points is None or away_points is None:
        return None
    if home_points > away_points:
        return "home"
    if away_points > home_points:
        return "away"
    return None


def build_game_card(game: dict, predictions: list[dict], odds: list[dict],
                     season: int, week: int, ap_rank_by_team: dict[int, int]) -> dict:
    market_margin = market_avg_margin(odds)

    model_rows = []
    for entry in predictions:
        source, pred = entry["source"], entry["prediction"]
        margin_home = float(pred["margin_home"]) if pred and pred["margin_home"] is not None else None
        win_prob_home = float(pred["win_prob_home"]) if pred and pred["win_prob_home"] is not None else None
        model_rows.append({
            "name": source["name"],
            "slug": source["slug"],
            "favored_abbr": favored_team_abbr(margin_home, game),
            "margin_display": em_dash_if_none(margin_home),
            "win_prob_display": win_prob_pct_display(win_prob_home),
            "divergence": divergence_chip(margin_home, market_margin),
        })

    market_rows = []
    for o in odds:
        margin_home = float(o["margin_home"]) if o["margin_home"] is not None else None
        win_prob_home = float(o["win_prob_home"]) if o["win_prob_home"] is not None else None
        market_rows.append({
            "provider": o["provider"],
            "favored_abbr": favored_team_abbr(margin_home, game),
            "margin_display": em_dash_if_none(margin_home),
            "win_prob_display": win_prob_pct_display(win_prob_home),
            "spread_home": o["spread_home"],
            "over_under": o["over_under"],
        })
    market_rows.sort(key=lambda r: PROVIDER_ORDER.get(r["provider"], len(PROVIDER_ORDER)))

    summary = parse_summary(game["id"], season, week)

    fpi = extract_fpi(predictions)
    home_fpi, away_fpi = fpi if fpi else (None, None)
    avg_fpi = (home_fpi + away_fpi) / 2 if fpi else None

    home_points, away_points = game["home_points"], game["away_points"]
    winner = game_winner(home_points, away_points)

    return {
        "id": game["id"],
        "start_date": game["start_date"],
        "tv": game["tv"],
        "neutral_site": game["neutral_site"],
        "venue": game["venue"],
        "home_school": game["home_school"], "home_abbr": game["home_abbr"],
        "home_logo_url": game["home_logo_url"], "home_logo_dark_url": game["home_logo_dark_url"],
        "home_color": game["home_color"], "home_fpi": home_fpi,
        "home_ap_rank": ap_rank_by_team.get(game["home_team_id"]),
        "away_school": game["away_school"], "away_abbr": game["away_abbr"],
        "away_logo_url": game["away_logo_url"], "away_logo_dark_url": game["away_logo_dark_url"],
        "away_color": game["away_color"], "away_fpi": away_fpi,
        "away_ap_rank": ap_rank_by_team.get(game["away_team_id"]),
        "model_rows": model_rows,
        "market_rows": market_rows,
        "sort_key": market_closeness_key(odds),
        "avg_fpi": avg_fpi,
        "summary": summary,
        "home_points": home_points,
        "away_points": away_points,
        "final": home_points is not None and away_points is not None,
        "winner": winner,
    }


def render_week(conn, env: Environment, season: int, week: int, season_type: str,
                 all_weeks: list[tuple[int, int, str]]) -> None:
    games = fetch_week_games(conn, season, week, season_type)
    if not games:
        log(f"no games for {season} {season_type} week {week}, skipping")
        return

    game_ids = [g["id"] for g in games]
    predictions_by_game = fetch_latest_predictions(conn, game_ids)
    odds_by_game = fetch_latest_odds(conn, game_ids)
    ap_rank_by_team = fetch_ap_ranks(conn, season, week, season_type)

    cards = [
        build_game_card(g, predictions_by_game[g["id"]], odds_by_game[g["id"]], season, week, ap_rank_by_team)
        for g in games
    ]

    teams_seen = {}
    for g, c in zip(games, cards):
        for prefix in ("home", "away"):
            # teams.conference stores CFBD's display name ("Big Ten"), not
            # the "B1G" query-filter code config.CONFERENCE holds.
            if g[f"{prefix}_conference"] != "Big Ten":
                continue
            school = g[f"{prefix}_school"]
            teams_seen.setdefault(school, {
                "school": school,
                "logo_url": g[f"{prefix}_logo_url"],
                "fpi": c[f"{prefix}_fpi"],
            })
    # Highest FPI first; teams with no FPI coverage sort last, alphabetically.
    teams = sorted(teams_seen.values(), key=lambda t: (t["fpi"] is None, -(t["fpi"] or 0), t["school"]))

    # Highest combined FPI first (marquee matchups float to the top); games
    # with no FPI coverage on either side fall back to closest-market-line.
    cards.sort(key=lambda c: (c["avg_fpi"] is None, -(c["avg_fpi"] or 0), c["sort_key"]))

    # Every game has the same set of active sources in the same order (see
    # fetch_latest_predictions), so any one game's list defines the glossary.
    glossary_sources = [
        {**entry["source"], "description": GLOSSARY_DESCRIPTIONS.get(entry["source"]["slug"])}
        for entry in predictions_by_game[games[0]["id"]]
    ]

    template = env.get_template("week.html")
    html = template.render(
        asset_prefix="../",
        season=season,
        week=week,
        season_type=season_type,
        cards=cards,
        teams=teams,
        glossary_sources=glossary_sources,
        all_weeks=all_weeks,
        current_week=(season, week, season_type),
        is_rankings=False,
    )

    out_dir = SITE_DIR / str(season)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / week_filename(week, season_type)
    out_path.write_text(html)
    log(f"wrote {os.path.relpath(out_path, ROOT)} ({len(cards)} games)")


def render_rankings(conn, env: Environment, season: int, week: int, season_type: str,
                     all_weeks: list[tuple[int, int, str]]) -> None:
    teams, sources = fetch_team_ratings(conn, season, week, season_type)

    glossary_sources = [
        {**s, "description": GLOSSARY_DESCRIPTIONS.get(s["slug"])} for s in sources
    ]

    def fpi_sort_key(team):
        fpi_cell = next((c for c in team["cells"] if c["slug"] == "fpi"), None)
        value = fpi_cell["value"] if fpi_cell else None
        return (value is None, -(value or 0), team["school"])

    # Highest FPI first by default; teams FPI hasn't rated sort last. Table
    # is still fully sortable client-side by clicking any column header.
    teams.sort(key=fpi_sort_key)

    template = env.get_template("rankings.html")
    html = template.render(
        asset_prefix="../",
        season=season,
        week=week,
        season_type=season_type,
        teams=teams,
        sources=sources,
        glossary_sources=glossary_sources,
        all_weeks=all_weeks,
        current_week=(season, week, season_type),
        is_rankings=True,
    )

    out_dir = SITE_DIR / str(season)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / rankings_filename(week, season_type)
    out_path.write_text(html)
    log(f"wrote {os.path.relpath(out_path, ROOT)} ({len(teams)} teams, {len(sources)} sources)")


def render_index(env: Environment, default_season: int, default_week: int, default_season_type: str) -> None:
    template = env.get_template("index.html")
    target = week_filename(default_week, default_season_type)
    html = template.render(asset_prefix="", season=default_season, week_path=target)
    (SITE_DIR / "index.html").write_text(html)
    log(f"wrote site/index.html -> redirects to {default_season}/{target}")


def copy_assets() -> None:
    dest = SITE_DIR / "assets"
    if dest.exists():
        shutil.rmtree(dest)
    if ASSETS_DIR.exists():
        shutil.copytree(ASSETS_DIR, dest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--season-type", default="regular")
    parser.add_argument("--all-weeks", action="store_true")
    args = parser.parse_args()

    SITE_DIR.mkdir(exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["eastern_kickoff"] = eastern_kickoff
    env.globals["week_filename"] = week_filename
    env.globals["rankings_filename"] = rankings_filename

    conn = db.get_connection()
    try:
        all_weeks = list_all_weeks(conn)
        if not all_weeks:
            log("no games in the database -- run collect.py first")
            return 1

        if args.year and args.week:
            targets = [(args.year, args.week, args.season_type)]
        elif args.all_weeks:
            targets = all_weeks
        else:
            targets = [determine_default_week(conn)]

        for season, week, season_type in targets:
            render_week(conn, env, season, week, season_type, all_weeks)
            render_rankings(conn, env, season, week, season_type, all_weeks)

        default_season, default_week, default_season_type = (
            targets[-1] if not args.all_weeks else determine_default_week(conn)
        )
        render_index(env, default_season, default_week, default_season_type)
        copy_assets()
    finally:
        conn.close()

    log("build complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
