"""
Circa Survivor 2026 — Probability Engine (Module 1/2)
=====================================================
Produces P(team wins) for every team in every leg.

Blend logic (your chosen "blend market + our model"):
  - When a real closing moneyline exists for a game -> use devigged market prob
    (market is the single best forecaster; it overrides our model).
  - Otherwise -> use our Elo model seeded from win totals.
The blend weight `market_weight` lets us mix the two when a partial/early
line exists (e.g. an opening line we only half-trust).
"""
import math
from . import data
from . import schedule


def elo_win_prob(elo_a: float, elo_b: float) -> float:
    """Standard Elo expected score: P(A beats B)."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def devig_moneyline(ml_team: int, ml_opp: int) -> float:
    """Two-way devig: convert American odds pair -> no-vig prob for `team`."""
    def implied(ml):
        return (-ml) / ((-ml) + 100) if ml < 0 else 100 / (ml + 100)
    p_team, p_opp = implied(ml_team), implied(ml_opp)
    return p_team / (p_team + p_opp)


def game_prob(away, home, *, neutral=False,
              moneyline=None, market_weight=1.0):
    """
    Return P(home wins), P(away wins).
    moneyline: optional dict {'home': -150, 'away': +130}; if given, blend.
    """
    hfa = 0.0 if neutral else data.HFA_ELO
    elo_home = data.BASE_ELO[home] + hfa
    elo_away = data.BASE_ELO[away]
    model_home = elo_win_prob(elo_home, elo_away)

    if moneyline is not None:
        mkt_home = devig_moneyline(moneyline["home"], moneyline["away"])
        p_home = market_weight * mkt_home + (1 - market_weight) * model_home
    else:
        p_home = model_home
    return p_home, 1 - p_home


def leg_probabilities(leg_id):
    """For one leg, return {team: P(team wins its game)} for all pic*able* teams."""
    leg = schedule.SCHEDULE[leg_id]
    out = {}
    for away, home in leg["games"]:
        neutral = (away, home) in schedule.NEUTRAL_SITE_GAMES
        p_home, p_away = game_prob(away, home, neutral=neutral)
        out[home] = p_home
        out[away] = p_away
    return out


def all_leg_probabilities():
    return {lid: leg_probabilities(lid) for lid in schedule.SCHEDULE}


if __name__ == "__main__":
    for lid, probs in all_leg_probabilities().items():
        print(f"\n=== {schedule.SCHEDULE[lid]['label']} ===")
        for team, p in sorted(probs.items(), key=lambda kv: -kv[1]):
            print(f"  {team:4s}  win prob {p:5.1%}")
