"""Exercises collect.run() end-to-end against mocked CFBD responses and a
fake in-memory Postgres connection, since no live DATABASE_URL or
CFBD_API_KEY is available in this environment. Real network/DB calls are
never made here.

This is the test that actually proves the acceptance criterion "killing one
source's endpoint does not stop the run": it makes cfbd_client.get_srs raise
and asserts every other source still writes rows and the run still exits 0.
"""
import json
from decimal import Decimal

import pytest

import cfbd_client
import collect
import conversions as c
from cfbd_client import CFBDError

YEAR, WEEK = 2026, 1

GAME_HOME_AWAY = {
    "id": 1001,
    "season": YEAR,
    "week": WEEK,
    "seasonType": "regular",
    "startDate": "2026-08-29T16:00:00.000Z",
    "neutralSite": False,
    "venue": "Fake Stadium",
    "homeId": 1,
    "homeTeam": "Ohio State",
    "homePoints": None,
    "awayId": 2,
    "awayTeam": "Indiana",
    "awayPoints": None,
}

GAME_NEUTRAL_SITE = {
    "id": 1002,
    "season": YEAR,
    "week": WEEK,
    "seasonType": "regular",
    "startDate": "2026-08-29T20:00:00.000Z",
    "neutralSite": True,
    "venue": "Neutral Field",
    "homeId": 1,
    "homeTeam": "Ohio State",
    "homePoints": None,
    "awayId": 2,
    "awayTeam": "Indiana",
    "awayPoints": None,
}

GAMES = [GAME_HOME_AWAY, GAME_NEUTRAL_SITE]

TEAMS = [
    {"id": 1, "school": "Ohio State", "abbreviation": "OSU", "conference": "Big Ten",
     "division": None, "logos": ["https://a/light.png", "https://a/dark.png"],
     "color": "#BB0000", "alternateColor": "#000000"},
    {"id": 2, "school": "Indiana", "abbreviation": "IU", "conference": "Big Ten",
     "division": None, "logos": ["https://b/light.png"],
     "color": "#990000", "alternateColor": "#FFFFFF"},
]

MODEL_SOURCES = [
    {"id": 1, "slug": "sp-plus", "output_type": "power_rating", "hfa": Decimal("2.5")},
    {"id": 2, "slug": "srs", "output_type": "power_rating", "hfa": Decimal("2.5")},
    {"id": 3, "slug": "elo", "output_type": "power_rating", "hfa": Decimal("2.5")},
    {"id": 4, "slug": "fpi", "output_type": "power_rating", "hfa": Decimal("2.5")},
    {"id": 5, "slug": "cfbd-pregame-wp", "output_type": "win_prob", "hfa": Decimal("2.5")},
]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._last_sql = None
        self._last_result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        normalized = " ".join(sql.split())
        if "max(updated_at) AS latest FROM teams" in normalized:
            self._last_result = ("one", {"latest": None})  # force a refresh
        elif normalized.startswith("SELECT * FROM model_sources"):
            self._last_result = ("all", MODEL_SOURCES)
        elif normalized == "SELECT id, school FROM teams":
            self._last_result = ("all", [{"id": t["id"], "school": t["school"]} for t in TEAMS])
        elif normalized.startswith("INSERT INTO teams"):
            self.conn.teams_inserted.append(params)
            self._last_result = None
        elif normalized.startswith("INSERT INTO games"):
            self.conn.games_inserted.append(params)
            self._last_result = None
        elif normalized.startswith("INSERT INTO predictions"):
            self.conn.predictions_inserted.append(params)
            self._last_result = None
        elif normalized.startswith("INSERT INTO odds_snapshots"):
            self.conn.odds_inserted.append(params)
            self._last_result = None
        elif normalized.startswith("INSERT INTO team_ratings"):
            self.conn.team_ratings_inserted.append(params)
            self._last_result = None
        elif normalized.startswith("INSERT INTO poll_rankings"):
            self.conn.poll_rankings_inserted.append(params)
            self._last_result = None
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {normalized[:80]}")

    def fetchone(self):
        kind, val = self._last_result
        assert kind == "one"
        return val

    def fetchall(self):
        kind, val = self._last_result
        assert kind == "all"
        return val


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.teams_inserted = []
        self.games_inserted = []
        self.predictions_inserted = []
        self.odds_inserted = []
        self.team_ratings_inserted = []
        self.poll_rankings_inserted = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _sp_ratings():
    return [
        {"year": YEAR, "team": "Ohio State", "conference": "Big Ten", "rating": 25.0},
        {"year": YEAR, "team": "Indiana", "conference": "Big Ten", "rating": 10.0},
    ]


def _elo_ratings():
    return [
        {"year": YEAR, "team": "Ohio State", "conference": "Big Ten", "elo": 2100},
        {"year": YEAR, "team": "Indiana", "conference": "Big Ten", "elo": 1850},
    ]


def _fpi_ratings():
    return [
        {"year": YEAR, "team": "Ohio State", "conference": "Big Ten", "fpi": 22.0},
        {"year": YEAR, "team": "Indiana", "conference": "Big Ten", "fpi": 8.0},
    ]


def _pregame_wp():
    return [
        {"season": YEAR, "week": WEEK, "gameId": 1001, "homeTeam": "Ohio State",
         "awayTeam": "Indiana", "spread": -14.0, "homeWinProbability": 0.82},
        {"season": YEAR, "week": WEEK, "gameId": 1002, "homeTeam": "Ohio State",
         "awayTeam": "Indiana", "spread": -10.0, "homeWinProbability": 0.74},
    ]


def _rankings():
    return [
        {"season": YEAR, "seasonType": "regular", "week": WEEK, "polls": [
            {"poll": "Coaches Poll", "ranks": [
                {"rank": 1, "school": "Ohio State", "points": 1600, "firstPlaceVotes": 30},
            ]},
            {"poll": "AP Top 25", "ranks": [
                {"rank": 2, "school": "Ohio State", "points": 1550, "firstPlaceVotes": 20},
                {"rank": 15, "school": "Indiana", "points": 800, "firstPlaceVotes": 0},
            ]},
        ]},
    ]


def _lines():
    return [
        {"id": 1001, "homeTeam": "Ohio State", "awayTeam": "Indiana", "lines": [
            {"provider": "DraftKings", "spread": -13.5, "spreadOpen": -12.5,
             "overUnder": 55.5, "overUnderOpen": 54.0,
             "homeMoneyline": -650, "awayMoneyline": 480},
        ]},
        {"id": 1002, "homeTeam": "Ohio State", "awayTeam": "Indiana", "lines": [
            {"provider": "DraftKings", "spread": -9.5, "spreadOpen": -8.5,
             "overUnder": 52.0, "overUnderOpen": 51.0,
             "homeMoneyline": -420, "awayMoneyline": 340},
            {"provider": "Bovada", "spread": -9.5, "spreadOpen": -8.5,
             "overUnder": 52.0, "overUnderOpen": 51.0},  # no moneyline published
        ]},
    ]


@pytest.fixture
def fake_conn(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(collect.db, "get_connection", lambda: conn)
    return conn


@pytest.fixture
def mocked_cfbd(monkeypatch):
    monkeypatch.setattr(cfbd_client, "get_teams", lambda **kw: TEAMS)
    monkeypatch.setattr(cfbd_client, "get_games", lambda **kw: GAMES)
    monkeypatch.setattr(cfbd_client, "get_games_media", lambda **kw: [])
    monkeypatch.setattr(cfbd_client, "get_sp", lambda **kw: _sp_ratings())

    def broken_srs(**kw):
        raise CFBDError("GET /ratings/srs -> 503: simulated outage")

    monkeypatch.setattr(cfbd_client, "get_srs", broken_srs)
    monkeypatch.setattr(cfbd_client, "get_elo", lambda **kw: _elo_ratings())
    monkeypatch.setattr(cfbd_client, "get_fpi", lambda **kw: _fpi_ratings())
    monkeypatch.setattr(cfbd_client, "get_pregame_wp", lambda **kw: _pregame_wp())
    monkeypatch.setattr(cfbd_client, "get_lines", lambda **kw: _lines())
    monkeypatch.setattr(cfbd_client, "get_rankings", lambda **kw: _rankings())


def test_one_broken_source_does_not_abort_the_run(fake_conn, mocked_cfbd, capsys):
    exit_code = collect.run(YEAR, WEEK, "regular")
    out = capsys.readouterr().out

    assert exit_code == 0, "run must succeed as long as at least one source works"
    assert "FAILED srs" in out
    assert "sources_attempted=7" in out
    assert "sources_succeeded=6" in out
    assert "sources_failed=['srs']" in out


def test_teams_and_games_are_upserted(fake_conn, mocked_cfbd):
    collect.run(YEAR, WEEK, "regular")
    assert len(fake_conn.teams_inserted) == 2
    assert len(fake_conn.games_inserted) == 2
    ohio_state = next(p for p in fake_conn.teams_inserted if p["id"] == 1)
    assert ohio_state["logo_url"] == "https://a/light.png"
    assert ohio_state["logo_dark_url"] == "https://a/dark.png"
    indiana = next(p for p in fake_conn.teams_inserted if p["id"] == 2)
    assert indiana["logo_dark_url"] is None  # only one logo published


def test_srs_writes_no_predictions_when_it_fails(fake_conn, mocked_cfbd):
    collect.run(YEAR, WEEK, "regular")
    srs_rows = [p for p in fake_conn.predictions_inserted if p["model_source_id"] == 2]
    assert srs_rows == []


def test_working_sources_write_one_prediction_per_game(fake_conn, mocked_cfbd):
    collect.run(YEAR, WEEK, "regular")
    sp_rows = [p for p in fake_conn.predictions_inserted if p["model_source_id"] == 1]
    assert len(sp_rows) == 2  # one per game, sp-plus didn't fail


def test_neutral_site_game_gets_zero_hfa_not_default(fake_conn, mocked_cfbd):
    collect.run(YEAR, WEEK, "regular")
    sp_rows = {p["game_id"]: p for p in fake_conn.predictions_inserted if p["model_source_id"] == 1}

    home_margin = sp_rows[1001]["margin_home"]   # regular game, hfa applied
    neutral_margin = sp_rows[1002]["margin_home"]  # neutral site, hfa = 0

    raw_diff = 25.0 - 10.0
    assert home_margin == pytest.approx(raw_diff + c.DEFAULT_HFA)
    assert neutral_margin == pytest.approx(raw_diff)
    assert home_margin != neutral_margin


def test_team_ratings_written_for_every_rated_team_regardless_of_opponent(fake_conn, mocked_cfbd):
    # Unlike predictions (one row per game, skipped if either side lacks a
    # rating), team_ratings gets one row per team a source rates, full stop.
    collect.run(YEAR, WEEK, "regular")
    sp_team_ratings = {
        r["team_id"]: r for r in fake_conn.team_ratings_inserted if r["model_source_id"] == 1
    }
    assert sp_team_ratings[1]["raw_value"] == pytest.approx(25.0)   # Ohio State
    assert sp_team_ratings[2]["raw_value"] == pytest.approx(10.0)   # Indiana
    assert sp_team_ratings[1]["season"] == YEAR
    assert sp_team_ratings[1]["week"] == WEEK  # pinned to this week, not just "latest"


def test_ap_poll_captured_but_not_other_polls(fake_conn, mocked_cfbd):
    # _rankings() has both a Coaches Poll and an AP Top 25 entry for Ohio
    # State with different ranks (1 vs 2) -- only AP Top 25 should land.
    collect.run(YEAR, WEEK, "regular")
    assert len(fake_conn.poll_rankings_inserted) == 2  # Ohio State + Indiana, AP only

    by_team = {r["team_id"]: r for r in fake_conn.poll_rankings_inserted}
    assert by_team[1]["poll"] == "AP Top 25"
    assert by_team[1]["poll_rank"] == 2   # AP rank, not the Coaches Poll's rank 1
    assert by_team[1]["week"] == WEEK
    assert by_team[2]["poll_rank"] == 15  # Indiana


def test_pregame_wp_backfills_margin_from_probability(fake_conn, mocked_cfbd):
    collect.run(YEAR, WEEK, "regular")
    wp_rows = {p["game_id"]: p for p in fake_conn.predictions_inserted if p["model_source_id"] == 5}

    assert wp_rows[1001]["win_prob_home"] == pytest.approx(0.82)
    assert wp_rows[1001]["raw_value"] == pytest.approx(0.82)  # raw_value = published probability, untouched
    assert wp_rows[1001]["margin_home"] == pytest.approx(c.margin_from_win_prob(0.82))


def test_lines_write_devigged_win_prob_and_signed_margin(fake_conn, mocked_cfbd):
    collect.run(YEAR, WEEK, "regular")
    assert len(fake_conn.odds_inserted) == 3

    row = next(o for o in fake_conn.odds_inserted if o["game_id"] == 1001)
    assert row["spread_home"] == -13.5
    assert row["margin_home"] == pytest.approx(13.5)  # home favored by 13.5 -> positive margin
    assert row["win_prob_home"] > 0.5  # home is the moneyline favorite (-650)

    expected_wp_home, expected_wp_away = c.devig_moneylines(-650, 480)
    assert row["win_prob_home"] == pytest.approx(expected_wp_home)
    assert expected_wp_home + expected_wp_away == pytest.approx(1.0)


def test_lines_without_a_moneyline_still_get_a_win_prob(fake_conn, mocked_cfbd):
    # Bovada published a spread but no moneyline for game 1002 -- win_prob_home
    # must still be filled in, derived from the spread the same way every
    # power-rating model source's margin becomes a win probability.
    collect.run(YEAR, WEEK, "regular")
    row = next(o for o in fake_conn.odds_inserted
               if o["game_id"] == 1002 and o["provider"] == "Bovada")
    assert row["moneyline_home"] is None
    assert row["win_prob_home"] == pytest.approx(c.win_prob_from_margin(9.5))


def test_each_source_commits_independently_of_a_later_failure(fake_conn, mocked_cfbd):
    # srs fails after sp-plus already succeeded; sp-plus's commit must survive.
    collect.run(YEAR, WEEK, "regular")
    assert fake_conn.commits >= 5  # teams + games + 4 successful model sources + lines
    assert fake_conn.rollbacks == 1  # only srs's failed transaction rolls back
