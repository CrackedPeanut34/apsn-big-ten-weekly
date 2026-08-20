"""Minimal client for the CollegeFootballData.com API v2.

Endpoint paths and field names below were verified against the live OpenAPI
spec at https://api.collegefootballdata.com/api-docs.json (spec version
5.24.0), not assumed from the v1 docs or third-party wrappers. Notably:

- /lines returns one BettingGame per game, each with a nested `lines[]`
  array of per-provider GameLine objects (provider, spread, spreadOpen,
  overUnder, overUnderOpen, homeMoneyline, awayMoneyline) -- NOT flat
  moneylineHome/moneylineAway fields on the game itself.
- /games has no `tv` field. Broadcast info lives on the separate
  /games/media endpoint (`outlet`), joined here by game id.
- Team logos come back as an unlabeled `logos` array (commonly
  [light, dark], not guaranteed) rather than separate light/dark fields.
"""
import requests

import config

TIMEOUT = 30


class CFBDError(RuntimeError):
    """Raised on any non-2xx response from the CFBD API."""


def _get(path: str, params: dict | None = None) -> list | dict:
    if not config.CFBD_API_KEY:
        raise CFBDError("CFBD_API_KEY is not set")
    resp = requests.get(
        f"{config.CFBD_BASE_URL}{path}",
        params=params or {},
        headers={"Authorization": f"Bearer {config.CFBD_API_KEY}"},
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise CFBDError(f"GET {path} {params} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def get_calendar(year: int) -> list[dict]:
    return _get("/calendar", {"year": year})


def get_teams(conference: str | None = None, year: int | None = None) -> list[dict]:
    params = {}
    if conference:
        params["conference"] = conference
    if year:
        params["year"] = year
    return _get("/teams", params)


def get_games(year: int, week: int, season_type: str = "regular",
              conference: str | None = None) -> list[dict]:
    params = {"year": year, "week": week, "seasonType": season_type}
    if conference:
        params["conference"] = conference
    return _get("/games", params)


def get_games_media(year: int, week: int, season_type: str = "regular",
                     conference: str | None = None) -> list[dict]:
    """/games/media requires `year`; week/conference narrow it further."""
    params = {"year": year, "week": week, "seasonType": season_type}
    if conference:
        params["conference"] = conference
    return _get("/games/media", params)


def get_lines(year: int, week: int, season_type: str = "regular",
              conference: str | None = None) -> list[dict]:
    params = {"year": year, "week": week, "seasonType": season_type}
    if conference:
        params["conference"] = conference
    return _get("/lines", params)


def get_sp(year: int) -> list[dict]:
    return _get("/ratings/sp", {"year": year})


def get_srs(year: int, conference: str | None = None) -> list[dict]:
    params = {"year": year}
    if conference:
        params["conference"] = conference
    return _get("/ratings/srs", params)


def get_elo(year: int, week: int | None = None,
            conference: str | None = None) -> list[dict]:
    # No seasonType param -- unlike get_games/get_lines/get_pregame_wp/
    # get_rankings above, this endpoint's parameters weren't confirmed
    # against the live OpenAPI spec (too large to fetch in full) and Elo is
    # a running/cumulative rating rather than recalculated fresh each week
    # (see model_sources seed data), so its postseason `week` semantics are
    # genuinely unverified. Re-check against real data once a postseason
    # week is actually being collected -- same spirit as
    # test_spread_sign_convention.py confirming a live-data assumption
    # rather than assuming it.
    params = {"year": year}
    if week:
        params["week"] = week
    if conference:
        params["conference"] = conference
    return _get("/ratings/elo", params)


def get_fpi(year: int, conference: str | None = None) -> list[dict]:
    params = {"year": year}
    if conference:
        params["conference"] = conference
    return _get("/ratings/fpi", params)


def get_pregame_wp(year: int, week: int, season_type: str = "regular") -> list[dict]:
    return _get("/metrics/wp/pregame", {"year": year, "week": week, "seasonType": season_type})


def get_rankings(year: int, week: int, season_type: str = "regular") -> list[dict]:
    """Every poll CFBD tracks (AP Top 25, Coaches Poll, FCS/D-II/D-III
    polls...) for one week. Shape: [{season, week, seasonType,
    polls: [{poll, ranks: [{rank, school, points, firstPlaceVotes, ...}]}]}]."""
    return _get("/rankings", {"year": year, "week": week, "seasonType": season_type})
