"""Empirically pins CFBD's /lines spread sign convention against a live game,
per the build brief: "needs to be verified empirically, not assumed... write
an assertion test that pins it."

No hardcoded game id: it pulls a real week of lines and finds a game where a
provider's moneyline shows a lopsided favorite. Moneyline sign is unambiguous
in American odds (large negative = heavy favorite) regardless of provider,
so it's used as ground truth to check that spread sign agrees with it.

Skipped entirely without a live CFBD_API_KEY -- this cannot be verified from
the OpenAPI schema alone, only from real data.
"""
import os

import pytest

import cfbd_client
import conversions as c

pytestmark = pytest.mark.skipif(
    not os.environ.get("CFBD_API_KEY"),
    reason="requires a live CFBD_API_KEY to fetch real /lines data",
)


def _find_lopsided_favorite(games):
    """Return (spread_home, moneyline_home) for the first line whose
    moneyline shows a favorite of at least 250 (a comfortable margin for a
    sign check), preferring the biggest one found."""
    best = None
    for game in games:
        for line in game.get("lines", []):
            ml_home = line.get("homeMoneyline")
            spread_home = line.get("spread")
            if ml_home is None or spread_home is None:
                continue
            if abs(ml_home) < 250:
                continue
            if best is None or abs(ml_home) > abs(best[1]):
                best = (spread_home, ml_home)
    return best


def test_spread_sign_matches_moneyline_sign_on_a_lopsided_game():
    # Scan a few recent weeks of regular-season games league-wide (not just
    # B1G) to maximize the odds of finding a lopsided cupcake matchup.
    found = None
    for year in (2025, 2024):
        for week in (1, 2, 3):
            games = cfbd_client.get_lines(year=year, week=week)
            found = _find_lopsided_favorite(games)
            if found:
                break
        if found:
            break

    assert found is not None, "no lopsided-favorite game found to check sign against"
    spread_home, ml_home = found

    # A heavy home moneyline favorite (ml_home very negative) must correspond
    # to a home-favored spread under SPREAD_SIGN_CONVENTION, i.e. a large
    # positive margin_home.
    margin_home = c.margin_from_spread(spread_home)
    if ml_home < 0:
        assert margin_home > 0, (
            f"home is a {ml_home} moneyline favorite but margin_from_spread "
            f"({spread_home}) -> {margin_home} says home is an underdog -- "
            f"SPREAD_SIGN_CONVENTION in conversions.py is backwards"
        )
    else:
        assert margin_home < 0, (
            f"home is a {ml_home} moneyline underdog but margin_from_spread "
            f"({spread_home}) -> {margin_home} says home is favored -- "
            f"SPREAD_SIGN_CONVENTION in conversions.py is backwards"
        )
