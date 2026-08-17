"""Exercises build.py end-to-end against a fake in-memory Postgres
connection and real Jinja templates, writing real HTML to a temp site/ dir.
No live DATABASE_URL is available in this environment, so DB reads are
faked the same way tests/test_collect_integration.py fakes them; the
templates and Jinja environment are the real ones from templates/.
"""
import datetime as dt
from decimal import Decimal

import pytest

import build

SEASON, WEEK = 2026, 1

HOME_TEAM_ID, AWAY_TEAM_ID = 1, 2

GAME_ROW = {
    "id": 1001,
    "season": SEASON,
    "week": WEEK,
    "season_type": "regular",
    "start_date": dt.datetime(2026, 8, 29, 16, 0, tzinfo=dt.timezone.utc),
    "tv": "FOX",
    "neutral_site": False,
    "venue": "Ohio Stadium",
    "home_points": None,
    "away_points": None,
    "home_school": "Ohio State", "home_abbr": "OSU",
    "home_logo_url": "https://a/light.png", "home_logo_dark_url": "https://a/dark.png",
    "home_color": "#BB0000", "home_alt_color": "#000000", "home_conference": "Big Ten",
    "away_school": "Indiana", "away_abbr": "IU",
    "away_logo_url": "https://b/light.png", "away_logo_dark_url": None,
    "away_color": "#990000", "away_alt_color": "#FFFFFF", "away_conference": "Big Ten",
}

MODEL_SOURCES = [
    {"id": 1, "name": "SP+", "slug": "sp-plus", "homepage_url": "https://espn.com/sp",
     "output_type": "power_rating", "hfa": Decimal("2.5"), "active": True,
     "notes": "Test note for SP+."},
    {"id": 2, "name": "SRS", "slug": "srs", "homepage_url": "https://cfbd.com/srs",
     "output_type": "power_rating", "hfa": Decimal("2.5"), "active": True,
     "notes": "Test note for SRS."},
    {"id": 3, "name": "FPI", "slug": "fpi", "homepage_url": "https://espn.com/fpi",
     "output_type": "power_rating", "hfa": Decimal("2.5"), "active": True,
     "notes": "Test note for FPI."},
]

# SP+ has a real row; SRS has none for this game -> must render as em dash.
PREDICTIONS = [
    {"game_id": 1001, "model_source_id": 1, "margin_home": 13.0, "win_prob_home": 0.80,
     "collected_at": dt.datetime(2026, 8, 27, 10, 0, tzinfo=dt.timezone.utc)},
]

ODDS = [
    {"game_id": 1001, "provider": "DraftKings", "margin_home": 10.0, "win_prob_home": 0.74,
     "spread_home": -10.0, "over_under": 55.5,
     "collected_at": dt.datetime(2026, 8, 28, 9, 0, tzinfo=dt.timezone.utc)},
]

TEAMS = [
    {"id": 1, "school": "Ohio State", "logo_url": "https://a/light.png"},
    {"id": 2, "school": "Indiana", "logo_url": "https://b/light.png"},
]

# Only SP+ and FPI have team_ratings rows -- SRS must render as em dash on
# the rankings page too, same as it does per-game. Indiana's FPI (5.0) is
# lower than Ohio State's (20.0) despite sorting first alphabetically, so
# the default-sort tests can tell "sorted by FPI" apart from "alphabetical".
# Both rows also double as the full national pool (no other teams exist in
# this fixture), so Ohio State is nationally No. 1 and Indiana No. 2 on
# both SP+ and FPI.
TEAM_RATINGS = [
    {"team_id": 1, "model_source_id": 1, "raw_value": Decimal("25.0"), "week": WEEK,
     "collected_at": dt.datetime(2026, 8, 27, 10, 0, tzinfo=dt.timezone.utc)},
    {"team_id": 2, "model_source_id": 1, "raw_value": Decimal("10.0"), "week": WEEK,
     "collected_at": dt.datetime(2026, 8, 27, 10, 0, tzinfo=dt.timezone.utc)},
    {"team_id": 1, "model_source_id": 3, "raw_value": Decimal("20.0"), "week": WEEK,
     "collected_at": dt.datetime(2026, 8, 27, 10, 0, tzinfo=dt.timezone.utc)},
    {"team_id": 2, "model_source_id": 3, "raw_value": Decimal("5.0"), "week": WEEK,
     "collected_at": dt.datetime(2026, 8, 27, 10, 0, tzinfo=dt.timezone.utc)},
]

# Ohio State is AP-ranked, Indiana isn't (unranked -> no poll_rankings row).
AP_RANKINGS = [
    {"team_id": 1, "poll_rank": 3},
]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        n = " ".join(sql.split())
        if "GROUP BY season, week" in n:
            self._result = ("all", [{"season": SEASON, "week": WEEK,
                                      "week_start": GAME_ROW["start_date"]}])
        elif "SELECT DISTINCT season, week FROM games" in n:
            self._result = ("all", [{"season": SEASON, "week": WEEK}])
        elif n.startswith("SELECT g.*"):
            self._result = ("all", [GAME_ROW])
        elif "FROM model_sources WHERE active = TRUE" in n:
            self._result = ("all", MODEL_SOURCES)
        elif "FROM predictions p" in n:
            self._result = ("all", PREDICTIONS)
        elif "FROM odds_snapshots o" in n:
            self._result = ("all", ODDS)
        elif "max(t) AS latest" in n:
            self._result = ("one", {"latest": ODDS[0]["collected_at"]})
        elif n.startswith("SELECT id, school, logo_url FROM teams"):
            self._result = ("all", TEAMS)
        elif "FROM team_ratings tr" in n:
            self._result = ("all", TEAM_RATINGS)
        elif "FROM poll_rankings pr" in n:
            self._result = ("all", AP_RANKINGS)
        elif "GROUP BY t.id" in n:
            # GAME_ROW is unplayed (points still None) -> both teams 0-0.
            self._result = ("all", [{"team_id": 1, "wins": 0, "losses": 0},
                                     {"team_id": 2, "wins": 0, "losses": 0}])
        else:
            raise AssertionError(f"unexpected SQL: {n[:100]}")

    def fetchone(self):
        kind, val = self._result
        assert kind == "one"
        return val

    def fetchall(self):
        kind, val = self._result
        assert kind == "all"
        return val


class FakeConnection:
    def cursor(self):
        return FakeCursor(self)

    def close(self):
        pass


@pytest.fixture
def wired(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "db", type("M", (), {"get_connection": staticmethod(lambda: FakeConnection())}))
    monkeypatch.setattr(build, "SITE_DIR", tmp_path / "site")
    monkeypatch.setattr(build, "SUMMARIES_DIR", tmp_path / "summaries")
    monkeypatch.setattr(build, "ASSETS_DIR", tmp_path / "assets_missing")
    return tmp_path


def test_build_writes_week_page_and_index(wired, monkeypatch):
    monkeypatch.setattr("sys.argv", ["build.py"])
    exit_code = build.main()
    assert exit_code == 0

    week_page = wired / "site" / str(SEASON) / f"week-{WEEK:02d}.html"
    index_page = wired / "site" / "index.html"
    assert week_page.exists()
    assert index_page.exists()

    html = week_page.read_text()
    assert "Ohio State" in html
    assert "Indiana" in html
    assert "SP+" in html
    assert "SRS" in html


def test_missing_model_source_renders_em_dash_not_zero(wired, monkeypatch):
    monkeypatch.setattr("sys.argv", ["build.py"])
    build.main()
    html = (wired / "site" / str(SEASON) / f"week-{WEEK:02d}.html").read_text()

    # SRS has no prediction row for this game -> em dash, and specifically
    # never a bare "0.0" that a reader could mistake for an actual rating.
    srs_row_start = html.index("SRS")
    srs_row_html = html[srs_row_start:srs_row_start + 400]
    assert "—" in srs_row_html


def test_game_with_no_summary_file_renders_cleanly(wired, monkeypatch):
    # SUMMARIES_DIR points at a directory that doesn't even exist.
    monkeypatch.setattr("sys.argv", ["build.py"])
    exit_code = build.main()
    assert exit_code == 0
    html = (wired / "site" / str(SEASON) / f"week-{WEEK:02d}.html").read_text()
    assert "summary-block" not in html


def test_divergence_chip_appears_when_model_diverges_from_market(wired, monkeypatch):
    # SP+ margin 13.0 vs market margin 10.0 -> 3.0 pt gap, at the threshold.
    monkeypatch.setattr("sys.argv", ["build.py"])
    build.main()
    html = (wired / "site" / str(SEASON) / f"week-{WEEK:02d}.html").read_text()
    assert "vs market" in html
    assert "+3.0 vs market" in html


def test_index_redirects_to_the_built_week(wired, monkeypatch):
    monkeypatch.setattr("sys.argv", ["build.py"])
    build.main()
    index_html = (wired / "site" / "index.html").read_text()
    assert f"{SEASON}/week-{WEEK:02d}.html" in index_html


RANKINGS_FILENAME = f"rankings-week-{WEEK:02d}.html"


def test_rankings_page_written_with_both_teams_and_sources(wired, monkeypatch):
    monkeypatch.setattr("sys.argv", ["build.py"])
    exit_code = build.main()
    assert exit_code == 0

    rankings_page = wired / "site" / str(SEASON) / RANKINGS_FILENAME
    assert rankings_page.exists()
    html = rankings_page.read_text()
    assert "Ohio State" in html
    assert "Indiana" in html
    assert "SP+" in html
    assert f"Week {WEEK}" in html


def test_rankings_page_em_dashes_a_source_with_no_team_rating(wired, monkeypatch):
    # Only SP+ and FPI have team_ratings rows in the fixture -- SRS must not
    # silently drop its column or show a bare 0.
    monkeypatch.setattr("sys.argv", ["build.py"])
    build.main()
    html = (wired / "site" / str(SEASON) / RANKINGS_FILENAME).read_text()
    srs_cell_start = html.index('data-sort-cell="srs"')
    assert "—" in html[srs_cell_start:srs_cell_start + 150]


def test_rankings_page_sorted_by_fpi_not_alphabetically(wired, monkeypatch):
    # Ohio State's FPI (20.0) beats Indiana's (5.0), so it must render first
    # even though "Indiana" sorts first alphabetically.
    monkeypatch.setattr("sys.argv", ["build.py"])
    build.main()
    html = (wired / "site" / str(SEASON) / RANKINGS_FILENAME).read_text()
    assert html.index("Ohio State") < html.index("Indiana")


def test_rankings_page_shows_win_loss_record(wired, monkeypatch):
    # GAME_ROW hasn't been played (points still None) -> both teams 0-0.
    monkeypatch.setattr("sys.argv", ["build.py"])
    build.main()
    html = (wired / "site" / str(SEASON) / RANKINGS_FILENAME).read_text()
    assert "Record" in html
    assert "0-0" in html


def test_rankings_page_shows_national_rank_and_ap_badge(wired, monkeypatch):
    # Ohio State (25.0) beats Indiana (10.0) on SP+, and only these two
    # teams exist in the fixture -- so Ohio State is nationally No. 1.
    # Ohio State is also the only AP-ranked team in the fixture (No. 3).
    monkeypatch.setattr("sys.argv", ["build.py"])
    build.main()
    html = (wired / "site" / str(SEASON) / RANKINGS_FILENAME).read_text()
    assert "No. 1" in html
    assert "AP 3" in html


def test_rankings_nav_link_appears_on_week_page(wired, monkeypatch):
    monkeypatch.setattr("sys.argv", ["build.py"])
    build.main()
    html = (wired / "site" / str(SEASON) / f"week-{WEEK:02d}.html").read_text()
    assert f'href="../{SEASON}/{RANKINGS_FILENAME}"' in html
