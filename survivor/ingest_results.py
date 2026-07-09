"""
Circa Survivor 2026 — Result Verifier
======================================
Reads completed-game scores from ESPN's scoreboard, decides survival per
Rule 6a (tie = LOSS), and records each entry's pick as survived/lost via
state.record_pick(). The state.json becomes authoritative for who's alive.

Auto-skips entries that:
  - are already marked dead (record_pick is a no-op for them anyway, but
    skipping keeps the report cleaner),
  - have no locked pick for the leg being verified,
  - have a pending pick whose game ESPN reports as not yet completed.

Holiday Contest Weeks resolve to the underlying ESPN week via the same
LEG_TO_ESPN_WEEK map ingest_lines uses.
"""
import json
import urllib.request

from . import schedule as sched
from . import state as state_mod
from .ingest_schedule import USER_AGENT, _team_abbr, fetch_week
from .ingest_lines import LEG_TO_ESPN_WEEK

STANDINGS_URL = (
    "https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season={year}"
)


def fetch_records(year=2026):
    """{team_abbr: {"wins", "losses", "ties", "summary"}} from ESPN standings.

    Pinned to `year` so we never show a stale prior season's finals (the
    unparameterized endpoint serves LAST season until the new one starts).
    Returns {} when the season hasn't started / ESPN hasn't seeded standings,
    so callers can suppress records cleanly in the offseason.
    """
    req = urllib.request.Request(
        STANDINGS_URL.format(year=year), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}

    out = {}
    for group in payload.get("children", []):
        for entry in (group.get("standings") or {}).get("entries", []):
            abbr = (entry.get("team") or {}).get("abbreviation")
            if not abbr:
                continue
            stats = {s.get("name"): s.get("value") for s in entry.get("stats", [])}
            w = int(stats.get("wins") or 0)
            l = int(stats.get("losses") or 0)
            t = int(stats.get("ties") or 0)
            if w + l + t == 0:
                continue  # season not started for this team; omit
            summary = f"{w}-{l}" + (f"-{t}" if t else "")
            out[_team_abbr(abbr)] = {"wins": w, "losses": l, "ties": t,
                                     "summary": summary}
    return out


def _parse_event(event):
    """Pull (away, home, away_score, home_score, completed, tied, winner)."""
    comp = (event.get("competitions") or [{}])[0]
    status_type = (comp.get("status") or {}).get("type") or {}
    completed = bool(status_type.get("completed"))
    home = away = None
    home_score = away_score = None
    for c in comp.get("competitors", []):
        ab = _team_abbr((c.get("team") or {}).get("abbreviation", ""))
        raw = c.get("score")
        try:
            score = int(raw) if raw not in (None, "") else None
        except (ValueError, TypeError):
            score = None
        if c.get("homeAway") == "home":
            home, home_score = ab, score
        elif c.get("homeAway") == "away":
            away, away_score = ab, score
    if not home or not away:
        return None
    winner = None
    tied = False
    if completed and home_score is not None and away_score is not None:
        if home_score > away_score:
            winner = home
        elif away_score > home_score:
            winner = away
        else:
            tied = True
    return {
        "away": away, "home": home,
        "away_score": away_score, "home_score": home_score,
        "completed": completed, "tied": tied, "winner": winner,
    }


def _outcomes_by_team(events_json):
    """{team: {'status': 'SURVIVED'|'LOST'|'TIED-LOSS'|'PENDING', 'game': info}}."""
    out = {}
    for ev in events_json.get("events", []):
        info = _parse_event(ev)
        if info is None:
            continue
        away, home = info["away"], info["home"]
        if not info["completed"]:
            out[home] = {"status": "PENDING", "game": info}
            out[away] = {"status": "PENDING", "game": info}
            continue
        if info["tied"]:
            # Rule 6a: a tie is a loss for the survivor pick.
            out[home] = {"status": "TIED-LOSS", "game": info}
            out[away] = {"status": "TIED-LOSS", "game": info}
            continue
        winner = info["winner"]
        loser = home if winner == away else away
        out[winner] = {"status": "SURVIVED", "game": info}
        out[loser]  = {"status": "LOST", "game": info}
    return out


def verify_leg(state, leg_id, year=2026):
    """For each alive entry with a pick locked in leg_id, look up the team's
    outcome in ESPN's payload and call state.record_pick(survived=…).

    Returns (results, n_games_in_payload) where
        results = [(entry, team, status_str, game_info_or_None), ...]
    """
    if leg_id not in LEG_TO_ESPN_WEEK:
        raise ValueError(f"Unknown leg {leg_id!r}; expected one of {sorted(LEG_TO_ESPN_WEEK)}")
    espn_week = LEG_TO_ESPN_WEEK[leg_id]
    events_json = fetch_week(year, espn_week)
    outcomes = _outcomes_by_team(events_json)

    results = []
    changes_written = False
    for e in sorted(state["entries"]):
        entry = state["entries"][e]
        team = entry["picks"].get(leg_id)
        if not team:
            continue  # no pick to verify
        if not entry["alive"]:
            results.append((e, team, "(entry already eliminated)", None))
            continue
        rec = outcomes.get(team)
        if rec is None:
            results.append((e, team, "NO-GAME-FOUND", None))
            continue
        status_str = rec["status"]
        info = rec["game"]
        if status_str == "PENDING":
            results.append((e, team, "PENDING", info))
            continue
        survived = (status_str == "SURVIVED")
        state_mod.record_pick(state, e, leg_id, team, survived=survived)
        changes_written = True
        results.append((e, team, status_str, info))

    if changes_written:
        state_mod.save_state(state)

    n_games = sum(1 for _ in events_json.get("events", []))
    return results, n_games
