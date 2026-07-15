"""
Circa Survivor 2026 — Live State Layer
======================================
Mutable, session-persistent layer on top of the static data/schedule.
Persists to `survivor/season_state.json` and is treated as the living
dispatch context for the season: edited weekly as picks lock, injuries
hit, lines move, and entries are eliminated.

Design rules:
  - Loading NEVER writes to disk (no `save_state` inside `load_state`).
  - `current_elo` returns BASE_ELO + adjustments, so seed values stay intact.
  - Moneyline overrides live under `leg_overrides[leg]["lines"]` and the
    solver/probability path consults them before falling back to Elo.
  - Entries are five independent buckets indexed "0".."4".
"""
import copy
import json
import os

from . import data

STATE_PATH = os.path.join(os.path.dirname(__file__), "season_state.json")

# Number of contest entries actually purchased. Was 5 in the planning phase;
# the user bought 2 for the 2026 contest. Everything downstream (solver, UI,
# CLI) sizes itself off the entries dict in state, so this constant is the
# single place to change.
N_ENTRIES = 2

DEFAULT_STATE = {
    "current_leg": "W1",
    "elo_adjustments": {},      # team -> delta Elo
    "leg_overrides": {},        # leg_id -> {"lines": {"HOME|AWAY": {...}}}
    "entries": {
        str(i): {
            "alive": True,
            "used_teams": [],
            "picks": {},        # leg_id -> team
            "bucket": None,     # default strategy: chalk | contrarian | conservation
            "leg_buckets": {},  # leg_id -> bucket override (falls back to `bucket`)
        }
        for i in range(N_ENTRIES)
    },
    "notes": {},
}


def load_state():
    """Return existing JSON state, or a fresh deep copy of DEFAULT_STATE.

    Never writes to disk. Returning a deep copy guarantees mutations by
    callers cannot accidentally edit the module-level DEFAULT_STATE.
    """
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return copy.deepcopy(DEFAULT_STATE)


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def current_elo(state):
    """The live team rating every projection prices from.

    Stack: BASE_ELO (June win-total anchor) + elo_adjustments (automatic
    results-Elo + manual nudges), optionally blended with ESPN FPI when
    power rankings have been ingested:

        final = (1 - w) * ours + w * (1500 + FPI_points * 25)

    w lives in state["power_rankings"]["weight"] so the blend follows the
    state file to every surface (solver, CLI, both UIs) automatically.
    """
    elo = dict(data.BASE_ELO)
    for team, delta in state.get("elo_adjustments", {}).items():
        elo[team] = elo.get(team, 1500.0) + delta

    pr = state.get("power_rankings") or {}
    fpi = pr.get("fpi") or {}
    w = pr.get("weight", 0.35)
    if fpi and w > 0:
        for team in elo:
            if team in fpi:
                elo[team] = (1 - w) * elo[team] + w * (1500.0 + fpi[team] * 25.0)
    return elo


def adjust_strength(state, team, delta, note=None):
    adj = state.setdefault("elo_adjustments", {})
    adj[team] = adj.get(team, 0.0) + delta
    if note:
        notes = state.setdefault("notes", {}).setdefault("strength", [])
        notes.append({"team": team, "delta": delta, "note": note})


def set_line(state, leg, away, home, ml_away, ml_home, market_weight=0.85):
    legs = state.setdefault("leg_overrides", {})
    leg_entry = legs.setdefault(leg, {})
    lines = leg_entry.setdefault("lines", {})
    lines[f"{home}|{away}"] = {
        "home": ml_home,
        "away": ml_away,
        "market_weight": market_weight,
    }


def record_pick(state, entry_idx, leg, team, survived=True):
    entry = state["entries"][str(entry_idx)]
    entry["picks"][leg] = team
    if team not in entry["used_teams"]:
        entry["used_teams"].append(team)
    if not survived:
        entry["alive"] = False


def set_bucket(state, entry_idx, bucket):
    state["entries"][str(entry_idx)]["bucket"] = bucket


def unlock_pick(state, entry_idx, leg):
    """Remove a locked pick for a leg that hasn't been played yet.

    Rebuilds used_teams from the remaining picks so the freed team becomes
    selectable again. Does NOT touch `alive` — never unlock a leg that has
    already been verified as a loss.
    """
    entry = state["entries"][str(entry_idx)]
    removed = entry["picks"].pop(leg, None)
    if removed is not None:
        entry["used_teams"] = [t for t in entry["used_teams"]
                               if t in entry["picks"].values()]
    return removed


def set_leg_bucket(state, entry_idx, leg, bucket):
    """Override the strategy bucket for one leg. `bucket=None` clears it,
    reverting that leg to the entry's default bucket."""
    entry = state["entries"][str(entry_idx)]
    lb = entry.setdefault("leg_buckets", {})
    if bucket is None:
        lb.pop(leg, None)
    else:
        lb[leg] = bucket


def effective_bucket(entry, leg_id):
    """The bucket in force for a given leg: per-leg override if set, else the
    entry's season default. `entry` is the entry dict, not an index."""
    return entry.get("leg_buckets", {}).get(leg_id) or entry.get("bucket")


def alive_entries(state):
    return [i for i, e in state["entries"].items() if e["alive"]]


def used_by(state, entry_idx):
    return list(state["entries"][str(entry_idx)]["used_teams"])


if __name__ == "__main__":
    s = load_state()
    print("current_leg     :", s["current_leg"])
    print("alive entries   :", alive_entries(s))
    print("elo_adjustments :", s["elo_adjustments"])
