"""All arithmetic on predictions and odds lives here, and nowhere else.

Bump CONVERSION_VERSION whenever any formula or constant below changes, then
recompute the season with one query against raw_value / raw_payload. Never
back-fill by editing raw_value -- it is what the source published, forever.
"""
from statistics import NormalDist

CONVERSION_VERSION = 1

DEFAULT_HFA = 2.5          # points, used where a source doesn't publish its own
WIN_PROB_SIGMA = 16.0      # normal-CDF sigma for margin -> win probability

_NORMAL = NormalDist(mu=0, sigma=1)

# --- Spread sign convention -------------------------------------------------
#
# CONFIRMED against live data on 2026-08-16 by
# tests/test_spread_sign_convention.py, which cross-checks spread sign
# against moneyline sign (unambiguous in American odds) on a real lopsided
# game. Re-run that test any time CFBD's API behavior is in doubt -- it's
# cheap and self-verifying, no hardcoded game id.
#
# CFBD's `spread` field on a GameLine is home-team-perspective, negative
# meaning the home team is favored (e.g. spread_home = -14.0 means home
# favored by 14).
SPREAD_SIGN_CONVENTION = "negative_favors_home"


def margin_from_power_rating(rating_home: float, rating_away: float, hfa: float | None) -> float:
    """power_rating -> margin_home. hfa=None uses DEFAULT_HFA; pass 0 explicitly
    for neutral-site games."""
    if hfa is None:
        hfa = DEFAULT_HFA
    return (rating_home - rating_away) + hfa


def margin_from_projected_score(projected_home: float, projected_away: float) -> float:
    """projected_score -> margin_home. No HFA term: it's already baked into
    both projected scores by whatever produced them."""
    return projected_home - projected_away


def margin_from_spread(spread_home: float) -> float:
    """spread -> margin_home, per SPREAD_SIGN_CONVENTION above."""
    return -spread_home


def win_prob_from_margin(margin_home: float, sigma: float = WIN_PROB_SIGMA) -> float:
    """margin -> win_prob_home via normal CDF.

    v1 placeholder: known to be wrong near the key numbers (3, 7, 10) and
    assumes constant variance across all margins. Isolated here so it can
    later be replaced with a curve fit to historical closing spreads by
    editing this one function and bumping CONVERSION_VERSION.
    """
    return _NORMAL.cdf(margin_home / sigma)


def margin_from_win_prob(win_prob_home: float, sigma: float = WIN_PROB_SIGMA) -> float:
    """Inverse of win_prob_from_margin. Used to back-fill margin_home for
    sources whose raw output is already a probability (e.g. CFBD pregame
    WP), so the table always has both columns per source."""
    win_prob_home = min(max(win_prob_home, 1e-9), 1 - 1e-9)
    return _NORMAL.inv_cdf(win_prob_home) * sigma


def moneyline_to_implied_prob(moneyline: float) -> float:
    """American odds -> implied probability, vig included."""
    if moneyline > 0:
        return 100.0 / (moneyline + 100.0)
    return -moneyline / (-moneyline + 100.0)


def devig_moneylines(moneyline_home: float, moneyline_away: float) -> tuple[float, float]:
    """Both sides' implied probabilities, vig removed proportionally so the
    pair sums to exactly 1.0. Returns (win_prob_home, win_prob_away)."""
    p_home = moneyline_to_implied_prob(moneyline_home)
    p_away = moneyline_to_implied_prob(moneyline_away)
    total = p_home + p_away
    return p_home / total, p_away / total
