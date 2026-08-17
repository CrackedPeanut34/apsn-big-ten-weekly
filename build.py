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
HEADLINE_WIN_PROB_CUTOFF = 0.85  # above this, lead with margin instead of win%
EASTERN = ZoneInfo("America/New_York")


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


# --- DB reads ----------------------------------------------------------------

def determine_default_week(conn) -> tuple[int, int]:
    """Picks the most relevant (season, week) already in the DB: the
    most-recently-started week that has kicked off, or if the season hasn't
    started yet, the earliest upcoming week."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT season, week, min(start_date) AS week_start
            FROM games
            GROUP BY season, week
            ORDER BY season DESC, week ASC
            """
        )
        rows = cur.fetchall()

    if not rows:
        raise RuntimeError("no games in the database -- run collect.py first")

    latest_season = rows[0]["season"]
    season_rows = [r for r in rows if r["season"] == latest_season]
    now = dt.datetime.now(dt.timezone.utc)

    past_or_current = [r for r in season_rows if r["week_start"] and r["week_start"] <= now]
    if past_or_current:
        chosen = max(past_or_current, key=lambda r: r["week"])
    else:
        chosen = season_rows[0]
    return chosen["season"], chosen["week"]


def list_all_weeks(conn) -> list[tuple[int, int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT season, week FROM games ORDER BY season, week")
        return [(r["season"], r["week"]) for r in cur.fetchall()]


def fetch_week_games(conn, season: int, week: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.*,
                   ht.school AS home_school, ht.abbreviation AS home_abbr,
                   ht.logo_url AS home_logo_url, ht.logo_dark_url AS home_logo_dark_url,
                   ht.color AS home_color, ht.alt_color AS home_alt_color,
                   at.school AS away_school, at.abbreviation AS away_abbr,
                   at.logo_url AS away_logo_url, at.logo_dark_url AS away_logo_dark_url,
                   at.color AS away_color, at.alt_color AS away_alt_color
            FROM games g
            JOIN teams ht ON ht.id = g.home_team_id
            JOIN teams at ON at.id = g.away_team_id
            WHERE g.season = %(season)s AND g.week = %(week)s
            ORDER BY g.start_date
            """,
            {"season": season, "week": week},
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


def fetch_most_recent_collection_time(conn, game_ids: list[int]):
    if not game_ids:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT max(t) AS latest FROM (
                SELECT max(collected_at) AS t FROM predictions WHERE game_id = ANY(%(ids)s)
                UNION ALL
                SELECT max(collected_at) AS t FROM odds_snapshots WHERE game_id = ANY(%(ids)s)
            ) x
            """,
            {"ids": game_ids},
        )
        return cur.fetchone()["latest"]


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


def format_headline(margin_home: float | None, win_prob_home: float | None,
                     home_abbr: str, away_abbr: str) -> str:
    """The card's single big number, built from the market baseline. Above
    ~85% win probability the percentage stops carrying information, so it
    leads with margin there instead."""
    if margin_home is None or win_prob_home is None:
        return "—"

    favored_abbr = home_abbr if margin_home >= 0 else away_abbr
    favored_wp = win_prob_home if margin_home >= 0 else (1 - win_prob_home)

    if favored_wp >= HEADLINE_WIN_PROB_CUTOFF:
        return f"{favored_abbr} by {abs(margin_home):.1f}"
    return f"{favored_abbr} {favored_wp * 100:.0f}% to win"


def em_dash_if_none(value, fmt: str = "{:.1f}") -> str:
    if value is None:
        return "—"
    return fmt.format(float(value))


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

def build_game_card(game: dict, predictions: list[dict], odds: list[dict],
                     season: int, week: int) -> dict:
    market_margin = market_avg_margin(odds)

    model_rows = []
    for entry in predictions:
        source, pred = entry["source"], entry["prediction"]
        margin_home = float(pred["margin_home"]) if pred and pred["margin_home"] is not None else None
        win_prob_home = float(pred["win_prob_home"]) if pred and pred["win_prob_home"] is not None else None
        model_rows.append({
            "name": source["name"],
            "homepage_url": source["homepage_url"],
            "margin_display": em_dash_if_none(margin_home),
            "win_prob_display": em_dash_if_none(win_prob_home * 100 if win_prob_home is not None else None, "{:.0f}%"),
            "divergence": divergence_chip(margin_home, market_margin),
        })

    market_rows = []
    for o in odds:
        margin_home = float(o["margin_home"]) if o["margin_home"] is not None else None
        win_prob_home = float(o["win_prob_home"]) if o["win_prob_home"] is not None else None
        market_rows.append({
            "provider": o["provider"],
            "margin_display": em_dash_if_none(margin_home),
            "win_prob_display": em_dash_if_none(win_prob_home * 100 if win_prob_home is not None else None, "{:.0f}%"),
            "spread_home": o["spread_home"],
            "over_under": o["over_under"],
        })

    headline_wp = None
    if market_margin is not None:
        wp_values = [float(o["win_prob_home"]) for o in odds if o.get("win_prob_home") is not None]
        headline_wp = sum(wp_values) / len(wp_values) if wp_values else None

    summary = parse_summary(game["id"], season, week)

    return {
        "id": game["id"],
        "start_date": game["start_date"],
        "tv": game["tv"],
        "neutral_site": game["neutral_site"],
        "venue": game["venue"],
        "home_school": game["home_school"], "home_abbr": game["home_abbr"],
        "home_logo_url": game["home_logo_url"], "home_logo_dark_url": game["home_logo_dark_url"],
        "home_color": game["home_color"],
        "away_school": game["away_school"], "away_abbr": game["away_abbr"],
        "away_logo_url": game["away_logo_url"], "away_logo_dark_url": game["away_logo_dark_url"],
        "away_color": game["away_color"],
        "headline": format_headline(market_margin, headline_wp, game["home_abbr"], game["away_abbr"]),
        "model_rows": model_rows,
        "market_rows": market_rows,
        "sort_key": market_closeness_key(odds),
        "summary": summary,
    }


def render_week(conn, env: Environment, season: int, week: int, all_weeks: list[tuple[int, int]]) -> None:
    games = fetch_week_games(conn, season, week)
    if not games:
        log(f"no games for {season} week {week}, skipping")
        return

    game_ids = [g["id"] for g in games]
    predictions_by_game = fetch_latest_predictions(conn, game_ids)
    odds_by_game = fetch_latest_odds(conn, game_ids)
    last_collected = fetch_most_recent_collection_time(conn, game_ids)

    cards = [
        build_game_card(g, predictions_by_game[g["id"]], odds_by_game[g["id"]], season, week)
        for g in games
    ]
    cards.sort(key=lambda c: c["sort_key"])

    last_collected_display = None
    if last_collected is not None:
        last_collected_display = last_collected.astimezone(EASTERN).strftime("%b %-d, %Y %-I:%M %p ET")

    template = env.get_template("week.html")
    html = template.render(
        asset_prefix="../",
        season=season,
        week=week,
        cards=cards,
        all_weeks=all_weeks,
        current_week=(season, week),
        last_collected_display=last_collected_display,
    )

    out_dir = SITE_DIR / str(season)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"week-{week:02d}.html"
    out_path.write_text(html)
    log(f"wrote {os.path.relpath(out_path, ROOT)} ({len(cards)} games)")


def render_index(env: Environment, default_season: int, default_week: int) -> None:
    template = env.get_template("index.html")
    html = template.render(asset_prefix="", season=default_season, week=default_week)
    (SITE_DIR / "index.html").write_text(html)
    log(f"wrote site/index.html -> redirects to {default_season}/week-{default_week:02d}.html")


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
    parser.add_argument("--all-weeks", action="store_true")
    args = parser.parse_args()

    SITE_DIR.mkdir(exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["eastern_kickoff"] = eastern_kickoff

    conn = db.get_connection()
    try:
        all_weeks = list_all_weeks(conn)
        if not all_weeks:
            log("no games in the database -- run collect.py first")
            return 1

        if args.year and args.week:
            targets = [(args.year, args.week)]
        elif args.all_weeks:
            targets = all_weeks
        else:
            targets = [determine_default_week(conn)]

        for season, week in targets:
            render_week(conn, env, season, week, all_weeks)

        default_season, default_week = targets[-1] if not args.all_weeks else determine_default_week(conn)
        render_index(env, default_season, default_week)
        copy_assets()
    finally:
        conn.close()

    log("build complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
