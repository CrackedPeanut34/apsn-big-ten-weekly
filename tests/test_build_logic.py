import pathlib

import pytest

import build


def test_week_filename_regular_has_no_prefix():
    assert build.week_filename(1, "regular") == "week-01.html"


def test_week_filename_postseason_gets_a_distinct_name():
    # Postseason week numbers restart from 1, same as the regular season --
    # these must never collide on disk.
    assert build.week_filename(1, "postseason") == "postseason-week-01.html"
    assert build.week_filename(1, "regular") != build.week_filename(1, "postseason")


def test_rankings_filename_regular_has_no_prefix():
    assert build.rankings_filename(3, "regular") == "rankings-week-03.html"


def test_rankings_filename_postseason_gets_a_distinct_name():
    assert build.rankings_filename(1, "postseason") == "postseason-rankings-week-01.html"


def test_chart_page_filename_regular_has_no_prefix():
    assert build.chart_page_filename(3, "regular") == "rankings-chart-week-03.html"


def test_chart_page_filename_postseason_gets_a_distinct_name():
    assert build.chart_page_filename(1, "postseason") == "postseason-rankings-chart-week-01.html"


def test_chart_data_filename_regular_has_no_prefix():
    assert build.chart_data_filename(3, "regular") == "rankings-chart-week-03.json"


def test_chart_data_filename_postseason_gets_a_distinct_name():
    assert build.chart_data_filename(1, "postseason") == "postseason-rankings-chart-week-01.json"


CHART_SOURCES = [
    {"id": 1, "name": "SP+", "slug": "sp-plus"},
    {"id": 2, "name": "Elo", "slug": "elo"},
]

CHART_TEAMS = [
    {
        "school": "Ohio State", "abbreviation": "OSU", "logo_url": "https://a/light.png", "color": "#BB0000",
        "ap_rank": 3, "record_display": "3-0 (1-2)",
        "cells": [{"slug": "sp-plus", "value": 25.0}, {"slug": "elo", "value": 2100.0}],
    },
    {
        "school": "Indiana", "abbreviation": None, "logo_url": "https://b/light.png", "color": "#990000",
        "ap_rank": None, "record_display": "1-2 (2-1)",
        "cells": [{"slug": "sp-plus", "value": None}, {"slug": "elo", "value": 1800.0}],
    },
]


def test_build_chart_export_shape_has_season_week_stats_teams():
    export = build.build_chart_export(2026, 1, "regular", CHART_TEAMS, CHART_SOURCES)
    assert export["season"] == 2026
    assert export["week"] == 1
    assert export["season_type"] == "regular"
    assert {s["key"] for s in export["stats"]} == {"ap_rank", "sp_plus", "elo"}
    assert {t["school"] for t in export["teams"]} == {"Ohio State", "Indiana"}


def test_build_chart_export_direction_asc_for_rank_desc_for_ratings():
    export = build.build_chart_export(2026, 1, "regular", CHART_TEAMS, CHART_SOURCES)
    directions = {s["key"]: s["direction"] for s in export["stats"]}
    assert directions["ap_rank"] == "asc"
    assert directions["sp_plus"] == "desc"
    assert directions["elo"] == "desc"


def test_build_chart_export_national_rank_is_not_included():
    # Dropped per explicit decision -- it's computed per rating source, not
    # as one unified number, so there's no single "national_rank" key.
    export = build.build_chart_export(2026, 1, "regular", CHART_TEAMS, CHART_SOURCES)
    keys = {s["key"] for s in export["stats"]}
    assert "national_rank" not in keys


def test_build_chart_export_slug_hyphens_become_json_safe_underscores():
    export = build.build_chart_export(2026, 1, "regular", CHART_TEAMS, CHART_SOURCES)
    ohio_state = next(t for t in export["teams"] if t["school"] == "Ohio State")
    assert ohio_state["values"]["sp_plus"] == 25.0
    assert "sp-plus" not in ohio_state["values"]


def test_build_chart_export_missing_value_is_null_not_dropped():
    export = build.build_chart_export(2026, 1, "regular", CHART_TEAMS, CHART_SOURCES)
    indiana = next(t for t in export["teams"] if t["school"] == "Indiana")
    assert indiana["values"]["sp_plus"] is None
    assert indiana["values"]["ap_rank"] is None
    assert indiana["values"]["elo"] == 1800.0


def test_build_chart_export_includes_team_abbreviation_for_scatter_labels():
    export = build.build_chart_export(2026, 1, "regular", CHART_TEAMS, CHART_SOURCES)
    ohio_state = next(t for t in export["teams"] if t["school"] == "Ohio State")
    assert ohio_state["abbr"] == "OSU"


def test_build_chart_export_falls_back_to_school_name_when_abbreviation_missing():
    export = build.build_chart_export(2026, 1, "regular", CHART_TEAMS, CHART_SOURCES)
    indiana = next(t for t in export["teams"] if t["school"] == "Indiana")
    assert indiana["abbr"] == "Indiana"


def test_build_chart_export_includes_record_display_for_head_to_head():
    export = build.build_chart_export(2026, 1, "regular", CHART_TEAMS, CHART_SOURCES)
    ohio_state = next(t for t in export["teams"] if t["school"] == "Ohio State")
    assert ohio_state["record_display"] == "3-0 (1-2)"


def test_market_avg_margin_averages_across_providers():
    odds = [{"margin_home": 10.0}, {"margin_home": 6.0}]
    assert build.market_avg_margin(odds) == pytest.approx(8.0)


def test_market_avg_margin_none_when_no_odds():
    assert build.market_avg_margin([]) is None


def test_market_avg_margin_skips_null_rows():
    odds = [{"margin_home": None}, {"margin_home": 4.0}]
    assert build.market_avg_margin(odds) == pytest.approx(4.0)


def test_divergence_chip_below_threshold_is_none():
    assert build.divergence_chip(10.0, 8.5) is None  # 1.5 pt gap


def test_divergence_chip_at_or_above_threshold_is_signed_gap():
    assert build.divergence_chip(14.0, 10.0) == pytest.approx(4.0)
    assert build.divergence_chip(6.0, 10.0) == pytest.approx(-4.0)


def test_divergence_chip_exactly_at_threshold_shows():
    assert build.divergence_chip(13.0, 10.0) == pytest.approx(3.0)


def test_divergence_chip_none_when_either_side_missing():
    assert build.divergence_chip(None, 10.0) is None
    assert build.divergence_chip(10.0, None) is None


def test_market_closeness_key_uses_tightest_book():
    odds = [{"margin_home": 10.0}, {"margin_home": -2.0}]
    assert build.market_closeness_key(odds) == pytest.approx(2.0)


def test_market_closeness_key_infinite_when_no_market_data():
    assert build.market_closeness_key([]) == float("inf")


def test_sorting_by_closeness_puts_tightest_game_first():
    blowout = {"sort_key": build.market_closeness_key([{"margin_home": 30.0}])}
    close_game = {"sort_key": build.market_closeness_key([{"margin_home": 1.5}])}
    no_market = {"sort_key": build.market_closeness_key([])}
    cards = [blowout, no_market, close_game]
    cards.sort(key=lambda c: c["sort_key"])
    assert cards == [close_game, blowout, no_market]


def test_game_winner_home_wins():
    assert build.game_winner(24, 17) == "home"


def test_game_winner_away_wins():
    assert build.game_winner(14, 21) == "away"


def test_game_winner_none_when_unplayed():
    assert build.game_winner(None, None) is None
    assert build.game_winner(10, None) is None


def test_game_winner_none_on_tie():
    assert build.game_winner(21, 21) is None


def test_em_dash_if_none_formats_value():
    assert build.em_dash_if_none(3.456) == "3.5"
    assert build.em_dash_if_none(None) == "—"


def test_em_dash_if_none_custom_format():
    assert build.em_dash_if_none(68.4, "{:.0f}%") == "68%"


def test_win_prob_pct_display_rounds_normally():
    assert build.win_prob_pct_display(0.684) == "68%"


def test_win_prob_pct_display_caps_at_99_percent():
    assert build.win_prob_pct_display(0.999) == "99%"
    assert build.win_prob_pct_display(1.0) == "99%"
    assert build.win_prob_pct_display(0.996) == "99%"  # would round to 100%


def test_win_prob_pct_display_none_is_em_dash():
    assert build.win_prob_pct_display(None) == "—"


def test_parse_summary_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "SUMMARIES_DIR", tmp_path)
    assert build.parse_summary(999999, 2026, 1) is None


def test_parse_summary_draft_status_not_rendered(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "SUMMARIES_DIR", tmp_path)
    week_dir = tmp_path / "2026" / "week-01"
    week_dir.mkdir(parents=True)
    (week_dir / "42.md").write_text(
        "---\ngame_id: 42\nauthor: Levi\nstatus: draft\n---\n\nDraft text.\n"
    )
    assert build.parse_summary(42, 2026, 1) is None


def test_parse_summary_published_renders_html_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "SUMMARIES_DIR", tmp_path)
    week_dir = tmp_path / "2026" / "week-01"
    week_dir.mkdir(parents=True)
    (week_dir / "42.md").write_text(
        "---\n"
        "game_id: 42\n"
        "author: Levi\n"
        "sources:\n"
        "  - title: Headline\n"
        "    url: https://example.com/a\n"
        "    outlet: Example Outlet\n"
        "status: published\n"
        "---\n\n"
        "Three sentences about the game.\n"
    )
    summary = build.parse_summary(42, 2026, 1)
    assert summary is not None
    assert summary["author"] == "Levi"
    assert summary["generated_by"] == "human"  # default
    assert "Three sentences" in summary["html"]
    assert summary["sources"][0]["url"] == "https://example.com/a"


def test_parse_summary_llm_generated_by_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "SUMMARIES_DIR", tmp_path)
    week_dir = tmp_path / "2026" / "week-01"
    week_dir.mkdir(parents=True)
    (week_dir / "7.md").write_text(
        "---\ngame_id: 7\nauthor: bot\ngenerated_by: llm\nstatus: published\n---\n\nDraft body.\n"
    )
    summary = build.parse_summary(7, 2026, 1)
    assert summary["generated_by"] == "llm"
