import pathlib

import pytest

import build


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


def test_format_headline_leads_with_win_prob_below_cutoff():
    headline = build.format_headline(6.0, 0.68, "OSU", "IU")
    assert headline == "OSU 68% to win"


def test_format_headline_leads_with_margin_above_cutoff():
    headline = build.format_headline(21.0, 0.91, "OSU", "IU")
    assert headline == "OSU by 21.0"


def test_format_headline_uses_away_team_when_underdog_at_home():
    # home margin is negative -> away team is favored
    headline = build.format_headline(-24.0, 0.05, "IU", "OSU")
    assert headline.startswith("OSU")
    assert "by 24.0" in headline


def test_format_headline_em_dash_when_no_market():
    assert build.format_headline(None, None, "OSU", "IU") == "—"


def test_em_dash_if_none_formats_value():
    assert build.em_dash_if_none(3.456) == "3.5"
    assert build.em_dash_if_none(None) == "—"


def test_em_dash_if_none_custom_format():
    assert build.em_dash_if_none(68.4, "{:.0f}%") == "68%"


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
