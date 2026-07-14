"""
Circa Survivor 2026 — Elo-from-results
=======================================
Keeps team ratings CURRENT all season. The June win-total Elo is only the
seed; every completed game moves ratings via a standard margin-of-victory
Elo update (FiveThirtyEight-style), written into state.elo_adjustments so
every projection surface (solver, Teams matrix, holiday reservations,
what-ifs) prices teams on what they've actually shown, not on preseason
expectations.

Update rule per completed game:
    e_home  = P(home wins) from CURRENT ratings (incl. HFA unless neutral)
    s_home  = 1 win / 0 loss / 0.5 tie
    mov     = ln(|margin|+1) * 2.2 / (0.001*|elo_diff_winner| + 2.2)
              (1.0 on a tie so a tie still nudges toward the underdog)
    delta   = K * mov * (s_home - e_home)      [K = 20]
    home += delta, away -= delta

Idempotency: processed games are tracked BY ESPN WEEK in
state["elo_processed"]["w<N>"] as "AWAY|HOME" keys. Contest legs that share
physical games (TXWEEK inside ESPN week 12, XMASWEEK inside 16) therefore
can never double-apply, and re-running verify is safe. A week whose games
are all final and processed is marked done in state["elo_weeks_done"] so
future syncs skip the network call entirely.

Entry points:
    sync_espn_week(state, year, espn_week, events_json=None) -> [updates]
    sync_leg(state, leg, year=2026, events_json=None)        -> [updates]
    pending_espn_weeks(state)                                -> [int, ...]
"""
import math

from . import schedule as sched
from . import state as state_mod
from .ingest_lines import LEG_TO_ESPN_WEEK
from .ingest_results import _parse_event
from .ingest_schedule import fetch_week
from . import data
from . import probability as prob_mod

K = 20.0

PROC_KEY = "elo_processed"    # {"w1": ["KC|LAC", ...], ...}
DONE_KEY = "elo_weeks_done"   # [1, 5, ...] espn weeks fully final+processed


def _mov_multiplier(margin, elo_diff_winner):
    if margin <= 0:  # tie
        return 1.0
    return math.log(margin + 1.0) * 2.2 / (0.001 * abs(elo_diff_winner) + 2.2)


def apply_game(state, info, espn_week):
    """Apply one completed game's Elo update. Returns update dict or None.

    `info` is ingest_results._parse_event output. Skips games already
    processed for this ESPN week. Mutates state (elo_adjustments + ledger)
    but does NOT save — callers batch and save once.
    """
    if not info or not info.get("completed"):
        return None
    away, home = info["away"], info["home"]
    key = f"{away}|{home}"
    wk = f"w{espn_week}"
    proc = state.setdefault(PROC_KEY, {}).setdefault(wk, [])
    if key in proc:
        return None
    if info.get("home_score") is None or info.get("away_score") is None:
        return None

    elo = state_mod.current_elo(state)
    neutral = (away, home) in sched.NEUTRAL_SITE_GAMES
    hfa = 0.0 if neutral else data.HFA_ELO
    e_home = prob_mod.elo_win_prob(elo[home] + hfa, elo[away])

    hs, as_ = info["home_score"], info["away_score"]
    if info.get("tied"):
        s_home, margin = 0.5, 0
        winner, loser = None, None
    elif hs > as_:
        s_home, margin = 1.0, hs - as_
        winner, loser = home, away
    else:
        s_home, margin = 0.0, as_ - hs
        winner, loser = away, home

    if winner is None:
        diff_w = 0.0
    else:
        diff_w = (elo[winner] + (hfa if winner == home else 0)) - \
                 (elo[loser] + (hfa if loser == home else 0))

    delta = K * _mov_multiplier(margin, diff_w) * (s_home - e_home)

    adj = state.setdefault("elo_adjustments", {})
    adj[home] = adj.get(home, 0.0) + round(delta, 2)
    adj[away] = adj.get(away, 0.0) - round(delta, 2)
    proc.append(key)

    return {"game": f"{away} {as_} @ {home} {hs}", "espn_week": espn_week,
            "delta_home": round(delta, 2), "home": home, "away": away}


def sync_espn_week(state, year, espn_week, events_json=None):
    """Apply Elo updates for every completed, unprocessed game in the week.

    Fetches ESPN if events_json isn't supplied. Marks the week done when all
    its games are final. Returns the list of applied updates (may be empty).
    Caller is responsible for state_mod.save_state when updates are returned.
    """
    done = state.setdefault(DONE_KEY, [])
    if espn_week in done:
        return []
    if events_json is None:
        events_json = fetch_week(year, espn_week)

    applied, all_final = [], True
    for ev in events_json.get("events", []):
        info = _parse_event(ev)
        if info is None:
            continue
        if not info["completed"]:
            all_final = False
            continue
        upd = apply_game(state, info, espn_week)
        if upd:
            applied.append(upd)
    if all_final and events_json.get("events"):
        done.append(espn_week)
    return applied


def sync_leg(state, leg, year=2026, events_json=None):
    """Sync ratings for the ESPN week underlying a contest leg."""
    wk = LEG_TO_ESPN_WEEK.get(leg)
    if wk is None:
        return []
    return sync_espn_week(state, year, wk, events_json)


def pending_espn_weeks(state):
    """ESPN weeks at/before the current leg that aren't fully processed.

    These are the only weeks a projection load needs to check — future
    weeks can't have results yet.
    """
    done = set(state.get(DONE_KEY, []))
    current = state.get("current_leg", "W1")
    order = [lid for lid in sched.LEG_ORDER if lid in sched.SCHEDULE]
    if current in order:
        candidates = order[: order.index(current) + 1]
    else:
        candidates = order
    weeks = []
    for lid in candidates:
        wk = LEG_TO_ESPN_WEEK.get(lid)
        if wk is not None and wk not in done and wk not in weeks:
            weeks.append(wk)
    return weeks
