"""Weekly collector. One entrypoint, safe to run more than once a day.

Refreshes teams, upserts this week's Big Ten games, then pulls each active
model source and each odds provider independently. A failure in any one
source is logged and skipped -- it never aborts the rest of the run. Teams
and games are upserted (ON CONFLICT DO UPDATE); predictions and
odds_snapshots are pure inserts, so re-running the same day just adds
another snapshot, which is the point (line movement is only observable
between snapshots).

Usage:
    python collect.py                       # auto-detect current season/week
    python collect.py --year 2026 --week 1   # explicit (backfill/testing)
"""
import argparse
import datetime as dt
import json
import sys

import cfbd_client
import config
import conversions as c
import db
from cfbd_client import CFBDError

TEAM_STALE_DAYS = 7


def log(msg: str) -> None:
    print(f"[collect] {msg}", flush=True)


def determine_current_week(year: int) -> tuple[int, str]:
    calendar = cfbd_client.get_calendar(year)
    now = dt.datetime.now(dt.timezone.utc)

    regular = sorted(
        (w for w in calendar if w.get("seasonType") == "regular"),
        key=lambda w: w["week"],
    )
    if not regular:
        raise RuntimeError(f"no regular-season weeks in CFBD calendar for {year}")

    def parse(ts: str) -> dt.datetime:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))

    for w in regular:
        if parse(w["startDate"]) <= now < parse(w["endDate"]):
            return w["week"], "regular"

    if now < parse(regular[0]["startDate"]):
        return regular[0]["week"], "regular"
    return regular[-1]["week"], "regular"


def refresh_teams_if_stale(conn, year: int) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(updated_at) AS latest FROM teams")
        latest = cur.fetchone()["latest"]

    if latest is not None:
        age = dt.datetime.now(dt.timezone.utc) - latest
        if age < dt.timedelta(days=TEAM_STALE_DAYS):
            log(f"teams fresh ({age.days}d old), skipping refresh")
            return

    # Unfiltered, not conference=B1G: Big Ten teams play nonconference
    # opponents (FCS cupcakes, other-conference teams) whose games still
    # need to be stored, which means their team row has to exist too or the
    # FK on games.away_team_id fails. One extra API call either way.
    teams = cfbd_client.get_teams(year=year)
    with conn.cursor() as cur:
        for t in teams:
            logos = t.get("logos") or []
            cur.execute(
                """
                INSERT INTO teams (id, school, abbreviation, conference, division,
                                    logo_url, logo_dark_url, color, alt_color, updated_at)
                VALUES (%(id)s, %(school)s, %(abbreviation)s, %(conference)s, %(division)s,
                        %(logo_url)s, %(logo_dark_url)s, %(color)s, %(alt_color)s, now())
                ON CONFLICT (id) DO UPDATE SET
                    school = EXCLUDED.school,
                    abbreviation = EXCLUDED.abbreviation,
                    conference = EXCLUDED.conference,
                    division = EXCLUDED.division,
                    logo_url = EXCLUDED.logo_url,
                    logo_dark_url = EXCLUDED.logo_dark_url,
                    color = EXCLUDED.color,
                    alt_color = EXCLUDED.alt_color,
                    updated_at = now()
                """,
                {
                    "id": t["id"],
                    "school": t["school"],
                    "abbreviation": t.get("abbreviation"),
                    "conference": t.get("conference"),
                    "division": t.get("division"),
                    "logo_url": logos[0] if len(logos) > 0 else None,
                    "logo_dark_url": logos[1] if len(logos) > 1 else None,
                    "color": t.get("color"),
                    "alt_color": t.get("alternateColor"),
                },
            )
    conn.commit()
    log(f"refreshed {len(teams)} teams")


def upsert_games(conn, year: int, week: int, season_type: str) -> list[dict]:
    games = cfbd_client.get_games(
        year=year, week=week, season_type=season_type, conference=config.CONFERENCE
    )

    tv_by_id: dict[int, str] = {}
    try:
        media = cfbd_client.get_games_media(
            year=year, week=week, season_type=season_type, conference=config.CONFERENCE
        )
        for m in media:
            outlet = m.get("outlet")
            if m.get("id") is not None and outlet:
                tv_by_id[m["id"]] = outlet
    except CFBDError as e:
        log(f"WARNING: /games/media failed, proceeding without TV info: {e}")

    with conn.cursor() as cur:
        for g in games:
            cur.execute(
                """
                INSERT INTO games (id, season, week, season_type, start_date, tv,
                                    home_team_id, away_team_id, neutral_site, venue,
                                    home_points, away_points, updated_at)
                VALUES (%(id)s, %(season)s, %(week)s, %(season_type)s, %(start_date)s, %(tv)s,
                        %(home_team_id)s, %(away_team_id)s, %(neutral_site)s, %(venue)s,
                        %(home_points)s, %(away_points)s, now())
                ON CONFLICT (id) DO UPDATE SET
                    start_date = EXCLUDED.start_date,
                    tv = EXCLUDED.tv,
                    neutral_site = EXCLUDED.neutral_site,
                    venue = EXCLUDED.venue,
                    home_points = EXCLUDED.home_points,
                    away_points = EXCLUDED.away_points,
                    updated_at = now()
                """,
                {
                    "id": g["id"],
                    "season": g["season"],
                    "week": g["week"],
                    "season_type": g["seasonType"],
                    "start_date": g.get("startDate"),
                    "tv": tv_by_id.get(g["id"]),
                    "home_team_id": g["homeId"],
                    "away_team_id": g["awayId"],
                    "neutral_site": bool(g.get("neutralSite")),
                    "venue": g.get("venue"),
                    "home_points": g.get("homePoints"),
                    "away_points": g.get("awayPoints"),
                },
            )
    conn.commit()
    log(f"upserted {len(games)} games for {year} week {week}")
    return games


def _hfa_for(game: dict, source_hfa) -> float:
    # source_hfa comes back from Postgres as a Decimal (NUMERIC column);
    # cast so it doesn't collide with the plain floats from the CFBD API.
    if game.get("neutralSite"):
        return 0.0
    return float(source_hfa) if source_hfa is not None else c.DEFAULT_HFA


def collect_power_rating_source(conn, source: dict, games: list[dict], ratings: list[dict],
                                 team_key: str = "team", rating_key: str = "rating") -> int:
    by_team = {r[team_key]: r for r in ratings}
    rows = 0
    with conn.cursor() as cur:
        for g in games:
            home = by_team.get(g["homeTeam"])
            away = by_team.get(g["awayTeam"])
            if home is None or away is None:
                continue  # source doesn't cover one side (e.g. new team) -> no row, renders as em dash

            rating_home = home[rating_key]
            rating_away = away[rating_key]
            hfa = _hfa_for(g, source["hfa"])
            raw_value = rating_home - rating_away
            margin_home = c.margin_from_power_rating(rating_home, rating_away, hfa)
            win_prob_home = c.win_prob_from_margin(margin_home)

            cur.execute(
                """
                INSERT INTO predictions (game_id, model_source_id, collected_at, raw_value,
                                          raw_type, raw_payload, margin_home, win_prob_home,
                                          conversion_version)
                VALUES (%(game_id)s, %(model_source_id)s, now(), %(raw_value)s, %(raw_type)s,
                        %(raw_payload)s, %(margin_home)s, %(win_prob_home)s, %(conversion_version)s)
                """,
                {
                    "game_id": g["id"],
                    "model_source_id": source["id"],
                    "raw_value": raw_value,
                    "raw_type": source["output_type"],
                    "raw_payload": json.dumps({"home": home, "away": away}),
                    "margin_home": margin_home,
                    "win_prob_home": win_prob_home,
                    "conversion_version": c.CONVERSION_VERSION,
                },
            )
            rows += 1
    conn.commit()
    return rows


def collect_team_ratings(conn, source: dict, ratings: list[dict], season: int, week: int,
                          team_key: str = "team", rating_key: str = "rating") -> int:
    """Every team a source rates, independent of who they're playing this
    week -- see 0003_team_ratings.sql for why collect_power_rating_source's
    per-game rows aren't enough on their own. Tagged with the collection
    week (0004_week_scoped_rankings.sql) so this week's rankings snapshot
    is pinned and never redrawn once a later week has its own rows."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, school FROM teams")
        team_id_by_school = {row["school"]: row["id"] for row in cur.fetchall()}

        rows = 0
        for r in ratings:
            team_id = team_id_by_school.get(r[team_key])
            if team_id is None:
                continue  # team not upserted yet -- refresh_teams_if_stale will catch it next run
            cur.execute(
                """
                INSERT INTO team_ratings (team_id, model_source_id, season, week, collected_at,
                                           raw_value, raw_payload, conversion_version)
                VALUES (%(team_id)s, %(model_source_id)s, %(season)s, %(week)s, now(),
                        %(raw_value)s, %(raw_payload)s, %(conversion_version)s)
                """,
                {
                    "team_id": team_id,
                    "model_source_id": source["id"],
                    "season": season,
                    "week": week,
                    "raw_value": r[rating_key],
                    "raw_payload": json.dumps(r),
                    "conversion_version": c.CONVERSION_VERSION,
                },
            )
            rows += 1
    conn.commit()
    return rows


AP_POLL_NAME = "AP Top 25"


def collect_poll_rankings(conn, year: int, week: int, season_type: str = "regular") -> int:
    """AP Top 25 only, out of the handful of polls CFBD returns (Coaches,
    FCS/D-II/D-III polls too) -- that's the one that was asked for. Same
    week-pinning as team_ratings: append-only, tagged with this week."""
    entries = cfbd_client.get_rankings(year=year, week=week, season_type=season_type)
    with conn.cursor() as cur:
        cur.execute("SELECT id, school FROM teams")
        team_id_by_school = {row["school"]: row["id"] for row in cur.fetchall()}

        rows = 0
        for entry in entries:
            if entry.get("week") != week:
                continue
            for poll in entry.get("polls", []):
                if poll["poll"] != AP_POLL_NAME:
                    continue
                for r in poll["ranks"]:
                    team_id = team_id_by_school.get(r["school"])
                    if team_id is None:
                        continue
                    cur.execute(
                        """
                        INSERT INTO poll_rankings (team_id, season, week, poll, poll_rank,
                                                    points, first_place_votes, collected_at)
                        VALUES (%(team_id)s, %(season)s, %(week)s, %(poll)s, %(poll_rank)s,
                                %(points)s, %(first_place_votes)s, now())
                        """,
                        {
                            "team_id": team_id,
                            "season": year,
                            "week": week,
                            "poll": poll["poll"],
                            "poll_rank": r["rank"],
                            "points": r.get("points"),
                            "first_place_votes": r.get("firstPlaceVotes"),
                        },
                    )
                    rows += 1
    conn.commit()
    return rows


def collect_pregame_wp_source(conn, source: dict, games: list[dict],
                               wp_rows: list[dict]) -> int:
    by_game_id = {w["gameId"]: w for w in wp_rows}
    game_ids = {g["id"] for g in games}
    rows = 0
    with conn.cursor() as cur:
        for game_id, w in by_game_id.items():
            if game_id not in game_ids:
                continue
            win_prob_home = w["homeWinProbability"]
            margin_home = c.margin_from_win_prob(win_prob_home)

            cur.execute(
                """
                INSERT INTO predictions (game_id, model_source_id, collected_at, raw_value,
                                          raw_type, raw_payload, margin_home, win_prob_home,
                                          conversion_version)
                VALUES (%(game_id)s, %(model_source_id)s, now(), %(raw_value)s, %(raw_type)s,
                        %(raw_payload)s, %(margin_home)s, %(win_prob_home)s, %(conversion_version)s)
                """,
                {
                    "game_id": game_id,
                    "model_source_id": source["id"],
                    "raw_value": win_prob_home,
                    "raw_type": source["output_type"],
                    "raw_payload": json.dumps(w),
                    "margin_home": margin_home,
                    "win_prob_home": win_prob_home,
                    "conversion_version": c.CONVERSION_VERSION,
                },
            )
            rows += 1
    conn.commit()
    return rows


def collect_lines(conn, year: int, week: int, season_type: str) -> int:
    betting_games = cfbd_client.get_lines(
        year=year, week=week, season_type=season_type, conference=config.CONFERENCE
    )
    rows = 0
    with conn.cursor() as cur:
        for bg in betting_games:
            for line in bg.get("lines", []):
                spread_home = line.get("spread")
                margin_home = c.margin_from_spread(spread_home) if spread_home is not None else None

                ml_home = line.get("homeMoneyline")
                ml_away = line.get("awayMoneyline")
                win_prob_home = None
                if ml_home is not None and ml_away is not None:
                    win_prob_home, _ = c.devig_moneylines(ml_home, ml_away)
                elif margin_home is not None:
                    # This provider didn't publish a moneyline for this game
                    # (common for early-season lines). Same margin -> win
                    # probability conversion already used for every power-
                    # rating model source, so the column is never just
                    # empty because one input was missing.
                    win_prob_home = c.win_prob_from_margin(margin_home)

                cur.execute(
                    """
                    INSERT INTO odds_snapshots (game_id, provider, collected_at, spread_home,
                                                 spread_open, over_under, over_under_open,
                                                 moneyline_home, moneyline_away, margin_home,
                                                 win_prob_home, conversion_version)
                    VALUES (%(game_id)s, %(provider)s, now(), %(spread_home)s, %(spread_open)s,
                            %(over_under)s, %(over_under_open)s, %(moneyline_home)s,
                            %(moneyline_away)s, %(margin_home)s, %(win_prob_home)s,
                            %(conversion_version)s)
                    """,
                    {
                        "game_id": bg["id"],
                        "provider": line.get("provider", "unknown"),
                        "spread_home": spread_home,
                        "spread_open": line.get("spreadOpen"),
                        "over_under": line.get("overUnder"),
                        "over_under_open": line.get("overUnderOpen"),
                        "moneyline_home": ml_home,
                        "moneyline_away": ml_away,
                        "margin_home": margin_home,
                        "win_prob_home": win_prob_home,
                        "conversion_version": c.CONVERSION_VERSION,
                    },
                )
                rows += 1
    conn.commit()
    return rows


def get_active_model_sources(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM model_sources WHERE active = TRUE ORDER BY id")
        return cur.fetchall()


def run(year: int, week: int, season_type: str = "regular") -> int:
    conn = db.get_connection()

    try:
        refresh_teams_if_stale(conn, year)
    except Exception as e:
        log(f"WARNING: team refresh failed, continuing with existing teams: {e}")

    try:
        games = upsert_games(conn, year, week, season_type)
    except Exception as e:
        log(f"FATAL: could not fetch/upsert games for {year} week {week}: {e}")
        return 1

    if not games:
        log(f"no Big Ten games found for {year} week {week}; nothing to collect")
        return 0

    sources = get_active_model_sources(conn)
    attempted, succeeded, failed = 0, 0, []
    total_rows = 0

    for source in sources:
        attempted += 1
        try:
            if source["slug"] == "sp-plus":
                ratings = cfbd_client.get_sp(year=year)
                rows = collect_power_rating_source(conn, source, games, ratings)
                rows += collect_team_ratings(conn, source, ratings, year, week)
            elif source["slug"] == "srs":
                # Not conference-filtered: nonconference opponents need a
                # rating too, or the home-minus-away differential can never
                # be computed (see the same fix on teams/games above).
                ratings = cfbd_client.get_srs(year=year)
                rows = collect_power_rating_source(conn, source, games, ratings)
                rows += collect_team_ratings(conn, source, ratings, year, week)
            elif source["slug"] == "elo":
                ratings = cfbd_client.get_elo(year=year, week=week)
                rows = collect_power_rating_source(conn, source, games, ratings, rating_key="elo")
                rows += collect_team_ratings(conn, source, ratings, year, week, rating_key="elo")
            elif source["slug"] == "fpi":
                ratings = cfbd_client.get_fpi(year=year)
                rows = collect_power_rating_source(conn, source, games, ratings, rating_key="fpi")
                rows += collect_team_ratings(conn, source, ratings, year, week, rating_key="fpi")
            elif source["slug"] == "cfbd-pregame-wp":
                wp_rows = cfbd_client.get_pregame_wp(year=year, week=week, season_type=season_type)
                rows = collect_pregame_wp_source(conn, source, games, wp_rows)
            else:
                log(f"WARNING: no collector wired up for model source '{source['slug']}', skipping")
                continue

            log(f"{source['slug']}: wrote {rows} rows")
            total_rows += rows
            succeeded += 1
        except Exception as e:
            conn.rollback()
            log(f"FAILED {source['slug']}: {e}")
            failed.append(source["slug"])

    attempted += 1
    try:
        rows = collect_lines(conn, year, week, season_type)
        log(f"lines: wrote {rows} odds_snapshots rows")
        total_rows += rows
        succeeded += 1
    except Exception as e:
        conn.rollback()
        log(f"FAILED lines: {e}")
        failed.append("lines")

    attempted += 1
    try:
        rows = collect_poll_rankings(conn, year, week, season_type)
        log(f"ap-poll: wrote {rows} rows")
        total_rows += rows
        succeeded += 1
    except Exception as e:
        conn.rollback()
        log(f"FAILED ap-poll: {e}")
        failed.append("ap-poll")

    conn.close()

    log(
        f"SUMMARY sources_attempted={attempted} sources_succeeded={succeeded} "
        f"sources_failed={failed} rows_written={total_rows}"
    )

    if succeeded == 0:
        log("FATAL: every source failed this run")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--season-type", default="regular")
    args = parser.parse_args()

    year = args.year or dt.datetime.now(dt.timezone.utc).year
    if args.week is not None:
        week, season_type = args.week, args.season_type
    else:
        week, season_type = determine_current_week(year)

    log(f"collecting {year} week {week} ({season_type})")
    return run(year, week, season_type)


if __name__ == "__main__":
    sys.exit(main())
