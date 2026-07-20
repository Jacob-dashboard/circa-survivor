"""
Circa Survivor 2026 — Monte Carlo strategy audit
=================================================
Plays out the solved plan thousands of times using each game's model win
probability, to answer "how strong is the strategy I've set?" against the
SPEC's own success metric: expected entries alive entering Thanksgiving,
with cross-entry decorrelation as the tiebreaker.

Correctness note — game-grouped draws: within one week, two entries on the
SAME team live or die together; two entries on OPPOSITE sides of one game
are perfectly anti-correlated (a straddle). Drawing each pick independently
would get both wrong. So each trial draws ONE outcome per game and resolves
every entry's pick against it — capturing real cross-entry correlation.

Honest limitation: this simulates SURVIVAL. It does not model contrarian
"field leverage" (needs pick-popularity data). A contrarian plan can look
weaker on pure survival yet be right, because it trades a little survival
for a bigger payout when the field's chalk busts. Read the survival numbers
as one axis, not the whole verdict.
"""
import random

from . import schedule as sched


def _game_for(leg, team):
    for away, home in sched.SCHEDULE[leg]["games"]:
        if team in (away, home):
            return away, home
    return None


def _legs():
    return [l for l in sched.LEG_ORDER if l in sched.SCHEDULE]


def simulate(plan, probs, entry_ids, n_trials=20000, seed=20260909):
    """Run the Monte Carlo. `plan` = {entry: {leg: team}}, `probs` =
    {leg: {team: win_prob}}. Returns a metrics dict (all rates in [0,1])."""
    legs = _legs()
    rng = random.Random(seed)
    n_entries = len(entry_ids)

    planned = {e: [l for l in legs if plan.get(e, {}).get(l)] for e in entry_ids}

    reach_tx = {e: 0 for e in entry_ids}
    reach_xmas = {e: 0 for e in entry_ids}
    win = {e: 0 for e in entry_ids}
    death_leg = {e: {} for e in entry_ids}
    alive_tx_hist = [0] * (n_entries + 1)      # index = # alive entering TXWEEK
    alive_xmas_hist = [0] * (n_entries + 1)
    # decorrelation: weeks where >=2 were alive and >=2 died the same week
    co_elim_weeks = 0
    at_risk_weeks = 0

    for _ in range(n_trials):
        alive = {e: True for e in entry_ids}
        for leg in legs:
            if leg == "TXWEEK":
                n = sum(alive.values())
                alive_tx_hist[n] += 1
                for e in entry_ids:
                    if alive[e]:
                        reach_tx[e] += 1
            if leg == "XMASWEEK":
                n = sum(alive.values())
                alive_xmas_hist[n] += 1
                for e in entry_ids:
                    if alive[e]:
                        reach_xmas[e] += 1

            alive_before = sum(alive.values())
            game_draw = {}
            died_this_leg = 0
            for e in entry_ids:
                if not alive[e]:
                    continue
                team = plan.get(e, {}).get(leg)
                if not team:
                    continue  # unplanned leg for this entry -> bye
                g = _game_for(leg, team)
                if g is None:
                    continue
                if g not in game_draw:
                    away, home = g
                    ph = probs.get(leg, {}).get(home, 0.5)
                    game_draw[g] = rng.random() < ph
                away, home = g
                home_wins = game_draw[g]
                survived = (team == home and home_wins) or (team == away and not home_wins)
                if not survived:
                    alive[e] = False
                    death_leg[e][leg] = death_leg[e].get(leg, 0) + 1
                    died_this_leg += 1
            if alive_before >= 2:
                at_risk_weeks += 1
                if died_this_leg >= 2:
                    co_elim_weeks += 1

        for e in entry_ids:
            if alive[e]:
                win[e] += 1

    N = float(n_trials)
    def _top_deaths(e):
        items = sorted(death_leg[e].items(), key=lambda kv: -kv[1])[:4]
        return [{"leg": l, "rate": round(c / N, 4)} for l, c in items]

    exp_alive_tx = sum(i * c for i, c in enumerate(alive_tx_hist)) / N
    exp_alive_xmas = sum(i * c for i, c in enumerate(alive_xmas_hist)) / N

    return {
        "trials": n_trials,
        "n_entries": n_entries,
        "planned_legs": {e: len(planned[e]) for e in entry_ids},
        "total_legs": len(legs),
        "per_entry": {
            e: {
                "reach_tx": round(reach_tx[e] / N, 4),
                "reach_xmas": round(reach_xmas[e] / N, 4),
                "win": round(win[e] / N, 4),
                "deadliest": _top_deaths(e),
            } for e in entry_ids
        },
        "portfolio": {
            "exp_alive_tx": round(exp_alive_tx, 4),
            "exp_alive_xmas": round(exp_alive_xmas, 4),
            "tx_dist": [round(c / N, 4) for c in alive_tx_hist],      # P(0),P(1),P(2)...
            "xmas_dist": [round(c / N, 4) for c in alive_xmas_hist],
            "any_alive_tx": round(1 - alive_tx_hist[0] / N, 4),
            "both_alive_tx": round(alive_tx_hist[n_entries] / N, 4),
            "co_elimination_rate": round(co_elim_weeks / at_risk_weeks, 4) if at_risk_weeks else 0.0,
        },
    }


def holiday_distinct(plan, entry_ids):
    """Deterministic decorrelation check at the holiday weeks: are the entries
    planned on DISTINCT teams (the hedge precondition)?"""
    out = {}
    for hw in ("TXWEEK", "XMASWEEK"):
        teams = [plan.get(e, {}).get(hw) for e in entry_ids]
        present = [t for t in teams if t]
        out[hw] = {
            "teams": teams,
            "distinct": len(set(present)) == len(present) and len(present) == len(entry_ids),
            "all_planned": len(present) == len(entry_ids),
        }
    return out
