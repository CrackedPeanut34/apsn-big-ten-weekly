import math

import pytest

import conversions as c


def test_power_rating_margin_uses_default_hfa_when_none():
    margin = c.margin_from_power_rating(rating_home=10.0, rating_away=4.0, hfa=None)
    assert margin == pytest.approx(6.0 + c.DEFAULT_HFA)


def test_power_rating_margin_neutral_site_zero_hfa():
    margin = c.margin_from_power_rating(rating_home=10.0, rating_away=4.0, hfa=0)
    assert margin == pytest.approx(6.0)


def test_power_rating_margin_uses_source_specific_hfa():
    margin = c.margin_from_power_rating(rating_home=0.0, rating_away=0.0, hfa=3.1)
    assert margin == pytest.approx(3.1)


def test_projected_score_margin():
    assert c.margin_from_projected_score(28.0, 17.0) == pytest.approx(11.0)
    assert c.margin_from_projected_score(17.0, 28.0) == pytest.approx(-11.0)


def test_spread_sign_home_favorite_is_negative_spread():
    # Home favored by 14 -> spread_home = -14 -> positive margin for home.
    assert c.margin_from_spread(-14.0) == pytest.approx(14.0)


def test_spread_sign_away_favorite_is_positive_spread():
    # Home is the underdog by 7 -> spread_home = +7 -> negative margin for home.
    assert c.margin_from_spread(7.0) == pytest.approx(-7.0)


def test_spread_sign_pick_em_is_zero():
    assert c.margin_from_spread(0.0) == pytest.approx(0.0)


def test_win_prob_from_margin_zero_is_fifty_percent():
    assert c.win_prob_from_margin(0.0) == pytest.approx(0.5)


def test_win_prob_from_margin_favors_home_on_positive_margin():
    wp = c.win_prob_from_margin(16.0)  # one full sigma
    assert wp > 0.5
    assert wp == pytest.approx(0.8413, abs=1e-3)


def test_win_prob_from_margin_symmetric():
    wp_pos = c.win_prob_from_margin(10.0)
    wp_neg = c.win_prob_from_margin(-10.0)
    assert wp_pos + wp_neg == pytest.approx(1.0)


def test_margin_from_win_prob_is_inverse_of_win_prob_from_margin():
    for margin in (-20.0, -3.5, 0.0, 7.0, 24.0):
        wp = c.win_prob_from_margin(margin)
        assert c.margin_from_win_prob(wp) == pytest.approx(margin, abs=1e-6)


def test_moneyline_favorite_implied_prob_above_half():
    assert c.moneyline_to_implied_prob(-150) > 0.5


def test_moneyline_underdog_implied_prob_below_half():
    assert c.moneyline_to_implied_prob(130) < 0.5


def test_moneyline_even_money_is_half():
    # +100 and -100 are both exactly break-even in American odds.
    assert c.moneyline_to_implied_prob(100) == pytest.approx(0.5)
    assert c.moneyline_to_implied_prob(-100) == pytest.approx(0.5)


def test_devig_moneylines_sums_to_one():
    wp_home, wp_away = c.devig_moneylines(-150, 130)
    assert wp_home + wp_away == pytest.approx(1.0)
    assert wp_home > wp_away  # home is the favorite here


def test_devig_moneylines_removes_vig_proportionally():
    # Raw implied probabilities here sum to > 1 (the vig); after de-vig they
    # must sum to exactly 1, with the favorite/underdog ordering preserved.
    raw_home = c.moneyline_to_implied_prob(-110)
    raw_away = c.moneyline_to_implied_prob(-110)
    assert raw_home + raw_away > 1.0  # sanity check there is vig to remove

    wp_home, wp_away = c.devig_moneylines(-110, -110)
    assert wp_home == pytest.approx(0.5)
    assert wp_away == pytest.approx(0.5)


def test_devig_moneylines_symmetric_with_swapped_sides():
    wp_home, wp_away = c.devig_moneylines(-200, 170)
    wp_away2, wp_home2 = c.devig_moneylines(170, -200)
    assert wp_home == pytest.approx(wp_home2)
    assert wp_away == pytest.approx(wp_away2)
