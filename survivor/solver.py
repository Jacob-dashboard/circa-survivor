"""
Circa Survivor 2026 — Portfolio Solver
======================================
State-aware optimizer over the 5-entry portfolio.

Objective (maximize):
    sum over (entry e, leg l, team t) of x[e,l,t] *
        wk_mult * (log p(t) - contrarian_weight(bucket_e) * popularity(t,l))
    - concentration_penalty * sum over (l,t) of wk_mult * z[l,t]
    [+ straddle_reward * sum over (l, game) of wk_mult * sv[l,game]   if endgame]

  - wk_mult            : holiday_weight on TXWEEK/XMASWEEK, else 1.
  - popularity(t,l)    : p(t) / max(probs[l].values())  -- DELIBERATELY max-normalized.
                         Normalizing by SUM is the known bug: in big slates it
                         crushes the penalty toward zero, the LP picks chalk,
                         and decorrelation never binds.
  - z[l,t] >= 0        : excess entries on (l,t) above 1. Linked
                         z >= (sum_e x[e,l,t]) - 1. Drives decorrelation.
  - sv[l,game] >= 0    : reward stacked ONLY when endgame=True. Bounded
                         sv <= sum(home_users) and sv <= sum(away_users), so
                         it is nonzero only when both sides are populated.
                         Decorrelation and straddle are OPPOSITE forces; do not
                         create sv vars outside endgame mode.

Constraints:
  - Exactly one team per (entry, not-yet-locked leg).
  - Each team usable at most once across an entry's remaining legs.
  - Holiday roster-exhaustion (Rules 8 & 9): every alive entry must reserve
    at least one team from each holiday pool that isn't already burned.
"""
import math

import pulp

from . import data
from . import probability as prob_mod
from . import schedule
from . import state as state_mod


# Per-bucket contrarian weight: how hard to avoid the popular/chalk pick.
# None (blank / no strategy input) = NO shaping at all — the model just
# maximizes win probability. "neutral" is kept as an accepted alias for
# backward compatibility but the UIs no longer offer it.
DEFAULT_CONTRARIAN_BY_BUCKET = {
    "chalk":        0.0,   # take the safest favorite
    "contrarian":   1.5,   # actively fade the obvious pick
    "conservation": 0.3,   # mild fade; conservation is about roster, not popularity
    "neutral":      0.0,   # legacy alias for blank
    None:           0.0,   # blank = no strategy input = pure win prob
}

# Per-bucket multiplier on the future-value (conservation) penalty. This is
# what makes "conservation" mean what its name says: hoard strong / holiday-
# pool teams and spend weak teams early. Chalk barely conserves (it just wants
# the safest team now); conservation conserves hard; blank not at all.
DEFAULT_FV_MULT_BY_BUCKET = {
    "chalk":        0.4,
    "contrarian":   1.0,
    "conservation": 2.2,
    "neutral":      0.0,   # legacy alias for blank
    None:           0.0,   # blank = no strategy input
}


def _effective_bucket(entry, leg_id):
    """Bucket in force for a leg: per-leg override, else the entry default."""
    return entry.get("leg_buckets", {}).get(leg_id) or entry.get("bucket")


# ---------------------------------------------------------------------------
# Probability helpers wired through live state
# ---------------------------------------------------------------------------

def _game_prob_live(away, home, elo, neutral=False, override=None):
    """Return (p_home, p_away) using state-adjusted Elo and an optional ML override."""
    hfa = 0.0 if neutral else data.HFA_ELO
    elo_home = elo[home] + hfa
    elo_away = elo[away]
    model_home = prob_mod.elo_win_prob(elo_home, elo_away)
    if override is not None:
        mkt = prob_mod.devig_moneyline(override["home"], override["away"])
        w = override.get("market_weight", 0.85)
        p_home = w * mkt + (1 - w) * model_home
    else:
        p_home = model_home
    return p_home, 1 - p_home


def leg_probs_live(state, leg_id):
    """{team: P(team wins)} for one leg, honoring state overrides."""
    elo = state_mod.current_elo(state)
    leg = schedule.SCHEDULE[leg_id]
    overrides = (
        state.get("leg_overrides", {}).get(leg_id, {}).get("lines", {})
    )
    out = {}
    for away, home in leg["games"]:
        neutral = (away, home) in schedule.NEUTRAL_SITE_GAMES
        override = overrides.get(f"{home}|{away}")
        p_home, p_away = _game_prob_live(away, home, elo, neutral, override)
        out[home] = p_home
        out[away] = p_away
    return out


# ---------------------------------------------------------------------------
# Horizon selection
# ---------------------------------------------------------------------------

def _weeks_to_solve(state, horizon):
    """Pick (legs, near_set, holiday_set) starting from state['current_leg'].

    near_set = next `horizon` non-holiday weeks from LEG_ORDER (committed).
    holiday_set = whichever holiday weeks are loaded (always reservations).
    """
    order = schedule.LEG_ORDER
    current = state.get("current_leg", order[0])
    try:
        start = order.index(current)
    except ValueError:
        start = 0

    near = []
    for lid in order[start:]:
        if lid in schedule.HOLIDAY_WEEKS:
            continue
        near.append(lid)
        if len(near) >= horizon:
            break

    holiday = [lid for lid in schedule.HOLIDAY_WEEKS if lid in schedule.SCHEDULE]
    near_set = set(near)
    holiday_set = set(holiday)
    legs = [lid for lid in order if lid in near_set or lid in holiday_set]
    return legs, near_set, holiday_set


# ---------------------------------------------------------------------------
# Future value: strong teams are scarce season-long resources
# ---------------------------------------------------------------------------

def future_value(team):
    """How much season-long value a team holds if NOT burned this week.

    Two components:
      * Season strength: (win_total - 8.5) / 3, floored at 0. A 11.5-win team
        (BAL, LAR) scores 1.0 — it will be a big favorite many more times this
        year. Sub-.500 teams score 0 — they have no future weeks where you'd
        want them, so burning them in a rare favorable spot is FREE.
      * Holiday-pool scarcity: +0.3 per holiday pool the team belongs to.
        Rules 8/9 make those pools mandatory, so pool members carry extra
        option value before the holidays (PHI, in both pools, is the single
        most expensive team to burn early).

    The solver subtracts future_value_weight * future_value(team) from every
    NON-holiday pick term. At the holiday weeks themselves the penalty is off:
    spending premium teams there is the entire point of conserving them.
    """
    wt = data.WIN_TOTALS.get(team, (8.5, None))[0]
    fv = max(0.0, (wt - 8.5) / 3.0)
    if team in schedule.TXWEEK_POOL:
        fv += 0.3
    if team in schedule.XMASWEEK_POOL:
        fv += 0.3
    return fv


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve(
    state,
    horizon=2,
    holiday_weight=2.0,
    min_prob=0.55,
    holiday_min_prob=0.50,
    contrarian_by_bucket=None,
    straddle_reward=0.35,
    concentration_penalty=0.25,
    future_value_weight=0.5,
    fv_mult_by_bucket=None,
    endgame=False,
):
    if contrarian_by_bucket is None:
        contrarian_by_bucket = DEFAULT_CONTRARIAN_BY_BUCKET
    if fv_mult_by_bucket is None:
        fv_mult_by_bucket = DEFAULT_FV_MULT_BY_BUCKET

    legs, near_set, holiday_set = _weeks_to_solve(state, horizon)
    probs = {lid: leg_probs_live(state, lid) for lid in legs}

    alive = state_mod.alive_entries(state)

    # ----- decision vars: x[e][l][t] in {0,1} ---------------------------------
    x = {}
    for e in alive:
        x[e] = {}
        entry = state["entries"][e]
        used = set(entry["used_teams"])
        picks = entry["picks"]
        bucket = entry.get("bucket")
        for lid in legs:
            if lid in picks:
                continue
            floor = holiday_min_prob if lid in holiday_set else min_prob
            if endgame:
                floor = min(floor, 0.40)
            x[e][lid] = {}
            for team, p in probs[lid].items():
                if team in used:
                    continue
                if p < floor:
                    continue
                x[e][lid][team] = pulp.LpVariable(
                    f"x_{e}_{lid}_{team}", cat="Binary"
                )

    model = pulp.LpProblem("circa_survivor", pulp.LpMaximize)

    # ----- objective: per-pick terms -----------------------------------------
    obj_terms = []
    for e in alive:
        entry_obj = state["entries"][e]
        for lid, team_vars in x[e].items():
            # Bucket is resolved PER LEG, so an entry can be contrarian one
            # week and conservation the next.
            bucket = _effective_bucket(entry_obj, lid)
            cw = contrarian_by_bucket.get(bucket, contrarian_by_bucket.get(None, 0.6))
            fv_mult = fv_mult_by_bucket.get(bucket, fv_mult_by_bucket.get(None, 1.0))
            wk_mult = holiday_weight if lid in holiday_set else 1.0
            top = max(probs[lid].values())
            for team, var in team_vars.items():
                p = probs[lid][team]
                pop = p / top
                coeff = wk_mult * (math.log(p) - cw * pop)
                # Conservation: burning a high-future-value team in an
                # ordinary week costs its option value, scaled by the leg's
                # bucket. Holiday weeks are exempt — that's where the
                # conserved teams get spent.
                if lid not in holiday_set:
                    coeff -= future_value_weight * fv_mult * future_value(team)
                obj_terms.append(coeff * var)

    # ----- decorrelation penalty: z[l,t] -------------------------------------
    z = {}
    for lid in legs:
        wk_mult = holiday_weight if lid in holiday_set else 1.0
        teams_in_leg = set()
        for e in alive:
            teams_in_leg.update(x[e].get(lid, {}).keys())
        for team in teams_in_leg:
            users = [x[e][lid][team] for e in alive if team in x[e].get(lid, {})]
            if len(users) <= 1:
                continue
            zv = pulp.LpVariable(f"z_{lid}_{team}", lowBound=0)
            z[(lid, team)] = zv
            model += zv >= pulp.lpSum(users) - 1
            obj_terms.append(-concentration_penalty * wk_mult * zv)

    # ----- straddle reward (ENDGAME ONLY) ------------------------------------
    straddles_found = []
    if endgame:
        for lid in legs:
            wk_mult = holiday_weight if lid in holiday_set else 1.0
            for away, home in schedule.SCHEDULE[lid]["games"]:
                home_users = [
                    x[e][lid][home] for e in alive if home in x[e].get(lid, {})
                ]
                away_users = [
                    x[e][lid][away] for e in alive if away in x[e].get(lid, {})
                ]
                if not home_users or not away_users:
                    continue
                sv = pulp.LpVariable(
                    f"sv_{lid}_{away}_{home}", lowBound=0
                )
                model += sv <= pulp.lpSum(home_users)
                model += sv <= pulp.lpSum(away_users)
                obj_terms.append(straddle_reward * wk_mult * sv)
                straddles_found.append((lid, away, home))

    model += pulp.lpSum(obj_terms)

    # ----- constraints --------------------------------------------------------
    # one team per (entry, open leg)
    for e in alive:
        for lid, team_vars in x[e].items():
            if not team_vars:
                continue
            model += pulp.lpSum(team_vars.values()) == 1, f"one_{e}_{lid}"

    # no team reused across an entry's remaining legs
    for e in alive:
        team_to_vars = {}
        for lid, team_vars in x[e].items():
            for team, var in team_vars.items():
                team_to_vars.setdefault(team, []).append(var)
        for team, vlist in team_to_vars.items():
            if len(vlist) > 1:
                model += pulp.lpSum(vlist) <= 1, f"unique_{e}_{team}"

    # holiday roster-exhaustion: must reserve at least one unused pool team
    pools = {"TXWEEK": schedule.TXWEEK_POOL, "XMASWEEK": schedule.XMASWEEK_POOL}
    for hw in holiday_set:
        pool = pools.get(hw, set())
        for e in alive:
            entry = state["entries"][e]
            if hw in entry["picks"]:
                continue
            unused_in_pool = pool - set(entry["used_teams"])
            if not unused_in_pool:
                continue
            selectable = [
                x[e][hw][t] for t in unused_in_pool if t in x[e].get(hw, {})
            ]
            if selectable:
                model += pulp.lpSum(selectable) >= 1, f"pool_{e}_{hw}"

    # ----- solve --------------------------------------------------------------
    # PuLP ships an x86_64 CBC that does not run on Apple Silicon. Prefer HiGHS
    # (pip install highspy) and fall back to CBC where it works.
    try:
        solver = pulp.HiGHS(msg=False)
    except Exception:
        solver = pulp.PULP_CBC_CMD(msg=False)
    model.solve(solver)
    status = pulp.LpStatus[model.status]

    # ----- extract results ----------------------------------------------------
    result = {}
    for e in alive:
        result[e] = dict(state["entries"][e]["picks"])  # carry locked picks
        for lid, team_vars in x[e].items():
            for team, var in team_vars.items():
                val = var.value()
                if val is not None and val > 0.5:
                    result[e][lid] = team
                    break

    meta = {
        "near_term": sorted(near_set),
        "holiday": sorted(holiday_set),
        "straddles": straddles_found,
        "status": status,
    }
    return result, probs, meta


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def print_solution(result, probs, meta):
    print(f"Status        : {meta['status']}")
    print(f"Near-term     : {meta['near_term']}")
    print(f"Holiday       : {meta['holiday']}")
    if meta["straddles"]:
        print(f"Straddles     : {meta['straddles']}")
    else:
        print("Straddles     : none (endgame off or no candidates)")
    near = set(meta["near_term"])
    holiday = set(meta["holiday"])
    leg_order = [lid for lid in schedule.LEG_ORDER if lid in near | holiday]
    for e in sorted(result.keys()):
        print(f"\nEntry {e}:")
        for lid in leg_order:
            team = result[e].get(lid)
            if team is None:
                continue
            tag = "[HOLIDAY/reserved]" if lid in holiday else "[committed]"
            p = probs.get(lid, {}).get(team)
            p_str = f"{p:5.1%}" if p is not None else "  n/a"
            print(f"  {lid:<10s} {team:<5s} p={p_str}  {tag}")
