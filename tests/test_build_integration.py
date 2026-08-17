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
    "home_color": "#BB0000", "home_alt_color": "#000000",
    "away_school": "Indiana", "away_abbr": "IU",
    "away_logo_url": "https://b/light.png", "away_logo_dark_url": None,
    "away_color": "#990000", "away_alt_color": "#FFFFFF",
}

MODEL_SOURCES = [
    {"id": 1, "name": "SP+", "slug": "sp-plus", "homepage_url": "https://espn.com/sp",
     "output_type": "power_rating", "hfa": Decimal("2.5"), "active": True},
    {"id": 2, "name": "SRS", "slug": "srs", "homepage_url": "https://cfbd.com/srs",
     "output_type": "power_rating", "hfa": Decimal("2.5"), "active": True},
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
