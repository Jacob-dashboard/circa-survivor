"""
Circa Survivor 2026 — HTML App Backend (FastAPI)
=================================================
Thin API layer over the existing modules. NO strategy logic lives here —
solver.py / state.py / ingest_*.py stay the single source of truth, shared
with the CLI and the Streamlit app (which keeps running as the backup UI).

Run:
    .venv/bin/uvicorn survivor.webapp:app --host 0.0.0.0 --port 8600

Endpoints:
    GET  /                    the SPA (survivor/webui/index.html)
    GET  /api/board           everything the Board needs in one payload
    GET  /api/plan            alternatives for one (entry, leg)
    POST /api/whatif          sandbox solve with an override; returns the diff
    POST /api/lock            record a pick (current or future = pin)
    POST /api/unlock          free a locked, unplayed week
    POST /api/bucket          set default or per-week bucket
    POST /api/advance         move current_leg
    GET  /api/market          line movement rows for a leg
    POST /api/lines           ingest DK moneylines into state for a leg
    GET  /api/injuries        high-severity injury feed
    POST /api/nudge           manual Elo adjustment
    GET  /api/check           integrity sweep
"""
import copy
import math
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from typing import Optional

from pydantic import BaseModel

from . import data
from . import schedule as sched
from . import solver
from . import state as state_mod
from . import ingest_lines, ingest_results, ingest_injuries

app = FastAPI(title="Circa Survivor 2026")

_WEBUI = os.path.join(os.path.dirname(__file__), "webui", "index.html")

DIAL_DEFAULTS = dict(horizon=17, min_prob=0.55, holiday_min_prob=0.50,
                     future_value_weight=0.5, endgame=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dials(horizon=None, min_prob=None, holiday_min_prob=None,
           future_value_weight=None, endgame=None):
    d = dict(DIAL_DEFAULTS)
    if horizon is not None:
        d["horizon"] = max(1, min(17, int(horizon)))
    if min_prob is not None:
        d["min_prob"] = float(min_prob)
    if holiday_min_prob is not None:
        d["holiday_min_prob"] = float(holiday_min_prob)
    if future_value_weight is not None:
        d["future_value_weight"] = float(future_value_weight)
    if endgame is not None:
        d["endgame"] = bool(endgame)
    return d


def _solve(state, d):
    return solver.solve(
        state, horizon=d["horizon"], min_prob=d["min_prob"],
        holiday_min_prob=d["holiday_min_prob"],
        future_value_weight=d["future_value_weight"], endgame=d["endgame"],
    )


def _loaded_legs():
    return [lid for lid in sched.LEG_ORDER if lid in sched.SCHEDULE]


def _rank_alternatives(state, res, probs, leg_id, entry_idx, floor, top_n=12):
    """Same ranking the Streamlit UI uses (kept in sync by the shared solver
    constants); model pick always included."""
    entry = state["entries"][entry_idx]
    used = set(entry["used_teams"])
    leg_probs = probs.get(leg_id, {})
    if not leg_probs:
        return []
    cands = []
    for team, p in leg_probs.items():
        if p < floor or team in used:
            continue
        stacks = sorted(o for o in res if o != entry_idx
                        and res.get(o, {}).get(leg_id) == team)
        cands.append({
            "team": team,
            "win_prob": round(p, 4),
            "in_tx": team in sched.TXWEEK_POOL,
            "in_xmas": team in sched.XMASWEEK_POOL,
            "stacks_with": stacks,
            "is_rec": res.get(entry_idx, {}).get(leg_id) == team,
            "ou": data.WIN_TOTALS.get(team, (None,))[0],
            "fv": round(solver.future_value(team), 2),
        })
    cands.sort(key=lambda c: -c["win_prob"])
    top = cands[:top_n]
    if not any(c["is_rec"] for c in top):
        rec = next((c for c in cands if c["is_rec"]), None)
        if rec:
            top.append(rec)
    return top


def _game_meta_json(leg_id):
    """fetch_game_meta with string keys for JSON; {} on any network failure."""
    try:
        raw = ingest_lines.fetch_game_meta(2026, leg_id)
    except Exception:
        return {}
    return {f"{away}|{home}": m for (away, home), m in raw.items()}


def _records_json():
    try:
        return {t: r["summary"] for t, r in ingest_results.fetch_records(2026).items()}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# SPA
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    # no-store: the SPA is one file that changes often; never serve stale UI.
    return FileResponse(_WEBUI, media_type="text/html",
                        headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Board payload
# ---------------------------------------------------------------------------

@app.get("/api/board")
def board(horizon: Optional[int] = None, min_prob: Optional[float] = None,
          holiday_min_prob: Optional[float] = None, future_value_weight: Optional[float] = None,
          endgame: Optional[bool] = None):
    d = _dials(horizon, min_prob, holiday_min_prob, future_value_weight, endgame)
    state = state_mod.load_state()
    try:
        res, probs, meta = _solve(state, d)
    except Exception as ex:
        raise HTTPException(500, f"solver failed: {ex}")

    return {
        "current_leg": state["current_leg"],
        "dials": d,
        "loaded_legs": [
            {"id": lid, "holiday": lid in sched.HOLIDAY_WEEKS}
            for lid in _loaded_legs()
        ],
        "entries": {
            e: {
                "alive": ent["alive"],
                "bucket": ent.get("bucket"),
                "leg_buckets": ent.get("leg_buckets", {}),
                "picks": ent["picks"],
                "used": ent["used_teams"],
            }
            for e, ent in state["entries"].items()
        },
        "plan": res,
        "probs": {lid: {t: round(p, 4) for t, p in teams.items()}
                  for lid, teams in probs.items()},
        "meta": meta,
        "game_meta": _game_meta_json(state["current_leg"]),
        "records": _records_json(),
        "win_totals": {t: wt for t, (wt, _) in data.WIN_TOTALS.items()},
        "pools": {"TXWEEK": sorted(sched.TXWEEK_POOL),
                  "XMASWEEK": sorted(sched.XMASWEEK_POOL)},
    }


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

@app.get("/api/plan")
def plan(entry: str, leg: str, horizon: Optional[int] = None, min_prob: Optional[float] = None,
         holiday_min_prob: Optional[float] = None, future_value_weight: Optional[float] = None,
         endgame: Optional[bool] = None):
    d = _dials(horizon, min_prob, holiday_min_prob, future_value_weight, endgame)
    state = state_mod.load_state()
    if entry not in state["entries"]:
        raise HTTPException(404, f"unknown entry {entry}")
    if leg not in sched.SCHEDULE:
        raise HTTPException(404, f"unknown leg {leg}")
    res, probs, meta = _solve(state, d)
    holiday = set(meta.get("holiday", []))
    floor = d["holiday_min_prob"] if leg in holiday else d["min_prob"]
    ent = state["entries"][entry]
    return {
        "locked": leg in ent["picks"],
        "locked_team": ent["picks"].get(leg),
        "model_pick": res.get(entry, {}).get(leg),
        "alternatives": _rank_alternatives(state, res, probs, leg, entry, floor),
        "game_meta": _game_meta_json(leg),
    }


class WhatIf(BaseModel):
    entry: str
    leg: str
    team: str
    horizon: Optional[int] = None
    min_prob: Optional[float] = None
    holiday_min_prob: Optional[float] = None
    future_value_weight: Optional[float] = None
    endgame: Optional[bool] = None


@app.post("/api/whatif")
def whatif(body: WhatIf):
    d = _dials(body.horizon, body.min_prob, body.holiday_min_prob,
               body.future_value_weight, body.endgame)
    state = state_mod.load_state()
    if body.entry not in state["entries"]:
        raise HTTPException(404, f"unknown entry {body.entry}")
    if body.leg not in sched.SCHEDULE:
        raise HTTPException(404, f"unknown leg {body.leg}")
    if body.team not in sched.teams_in_week(body.leg):
        raise HTTPException(400, f"{body.team} does not play in {body.leg}")
    if body.team in state["entries"][body.entry]["used_teams"]:
        raise HTTPException(409, f"entry {body.entry} already used {body.team}")
    res, probs, meta = _solve(state, d)

    sim = copy.deepcopy(state)
    state_mod.record_pick(sim, body.entry, body.leg, body.team, survived=True)
    try:
        sres, sprobs, smeta = _solve(sim, d)
    except Exception as ex:
        return {"status": f"error: {ex}"}

    scope = set(meta.get("near_term", [])) | set(meta.get("holiday", []))
    diff = []
    for lid in _loaded_legs():
        if lid not in scope or lid == body.leg:
            continue
        before = res.get(body.entry, {}).get(lid)
        after = sres.get(body.entry, {}).get(lid)
        diff.append({
            "leg": lid, "before": before, "after": after,
            "pb": round(probs.get(lid, {}).get(before, 0), 4) if before else None,
            "pa": round(sprobs.get(lid, {}).get(after, 0), 4) if after else None,
            "changed": before != after,
        })

    ripple = []
    for o in state["entries"]:
        if o == body.entry:
            continue
        for lid in _loaded_legs():
            if lid not in scope:
                continue
            b, a = res.get(o, {}).get(lid), sres.get(o, {}).get(lid)
            if b != a and lid not in state["entries"][o]["picks"]:
                ripple.append({"entry": o, "leg": lid, "before": b, "after": a})

    model_pick = res.get(body.entry, {}).get(body.leg)
    return {
        "status": smeta["status"],
        "model_pick": model_pick,
        "p_model": round(probs.get(body.leg, {}).get(model_pick, 0), 4) if model_pick else None,
        "p_choice": round(probs.get(body.leg, {}).get(body.team, 0), 4),
        "diff": diff,
        "ripple": ripple,
        "sim_plan": sres.get(body.entry, {}),
        "sim_probs": {lid: {t: round(p, 4) for t, p in tp.items()}
                      for lid, tp in sprobs.items()},
    }


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

class LockReq(BaseModel):
    entry: str
    leg: str
    team: str


@app.post("/api/lock")
def lock(body: LockReq):
    state = state_mod.load_state()
    if body.entry not in state["entries"]:
        raise HTTPException(404, f"unknown entry {body.entry}")
    if body.leg not in sched.SCHEDULE:
        raise HTTPException(404, f"unknown leg {body.leg}")
    pool = sched.teams_in_week(body.leg)
    if body.team not in pool:
        raise HTTPException(400, f"{body.team} not in {body.leg} pool")
    ent = state["entries"][body.entry]
    if body.team in ent["used_teams"] and ent["picks"].get(body.leg) != body.team:
        raise HTTPException(409, f"entry {body.entry} already used {body.team}")
    state_mod.record_pick(state, body.entry, body.leg, body.team, survived=True)
    state_mod.save_state(state)
    return {"ok": True, "entry": body.entry, "leg": body.leg, "team": body.team}


class UnlockReq(BaseModel):
    entry: str
    leg: str


@app.post("/api/unlock")
def unlock(body: UnlockReq):
    state = state_mod.load_state()
    if body.entry not in state["entries"]:
        raise HTTPException(404, f"unknown entry {body.entry}")
    removed = state_mod.unlock_pick(state, body.entry, body.leg)
    if removed is None:
        raise HTTPException(404, f"no lock on {body.leg} for entry {body.entry}")
    state_mod.save_state(state)
    return {"ok": True, "removed": removed}


class BucketReq(BaseModel):
    entry: str
    bucket: Optional[str] = None    # None/"" clears (per-week only)
    leg: Optional[str] = None       # omit -> set entry default


@app.post("/api/bucket")
def bucket(body: BucketReq):
    state = state_mod.load_state()
    if body.entry not in state["entries"]:
        raise HTTPException(404, f"unknown entry {body.entry}")
    b = body.bucket or None
    if b is not None and b not in ("chalk", "contrarian", "conservation", "neutral"):
        raise HTTPException(400, "bucket must be chalk|contrarian|conservation|neutral")
    if body.leg:
        state_mod.set_leg_bucket(state, body.entry, body.leg, b)
    else:
        state_mod.set_bucket(state, body.entry, b)
    state_mod.save_state(state)
    return {"ok": True}


class AdvanceReq(BaseModel):
    leg: str


@app.post("/api/advance")
def advance(body: AdvanceReq):
    state = state_mod.load_state()
    if body.leg not in sched.SCHEDULE:
        raise HTTPException(404, f"unknown leg {body.leg}")
    state["current_leg"] = body.leg
    state_mod.save_state(state)
    return {"ok": True, "current_leg": body.leg}


class NudgeReq(BaseModel):
    team: str
    delta: float
    note: Optional[str] = None


@app.post("/api/nudge")
def nudge(body: NudgeReq):
    state = state_mod.load_state()
    if body.team not in data.BASE_ELO:
        raise HTTPException(404, f"unknown team {body.team}")
    state_mod.adjust_strength(state, body.team, body.delta, note=body.note)
    state_mod.save_state(state)
    return {"ok": True,
            "cumulative": state["elo_adjustments"].get(body.team, 0)}


# ---------------------------------------------------------------------------
# Market / data
# ---------------------------------------------------------------------------

@app.get("/api/market")
def market(leg: str):
    if leg not in ingest_lines.LEG_TO_ESPN_WEEK:
        raise HTTPException(404, f"no ESPN week for {leg}")
    gm = _game_meta_json(leg)
    rows = []
    for key, m in gm.items():
        away, home = key.split("|")
        move = []
        sp_o, sp_c = m.get("spread_home_open"), m.get("spread_home")
        mlh_o, mlh_c = m.get("ml_home_open"), m.get("ml_home")
        if sp_o is not None and sp_c is not None and sp_o != sp_c:
            move.append(f"spread → {home if sp_c < sp_o else away}")
        if mlh_o is not None and mlh_c is not None and mlh_c != mlh_o:
            move.append(f"ML → {home if mlh_c < mlh_o else away}")
        rows.append({
            "away": away, "home": home,
            "kickoff": m.get("kickoff_display"),
            "spread_open": sp_o, "spread": sp_c,
            "ml_home_open": mlh_o, "ml_home": mlh_c,
            "ml_away_open": m.get("ml_away_open"), "ml_away": m.get("ml_away"),
            "total": m.get("total"),
            "moving": ", ".join(move),
        })
    return {"leg": leg, "rows": rows}


class LinesReq(BaseModel):
    leg: str


@app.post("/api/lines")
def lines(body: LinesReq):
    state = state_mod.load_state()
    try:
        applied, skipped = ingest_lines.ingest_lines_for_leg(state, body.leg)
    except Exception as ex:
        raise HTTPException(502, f"ESPN fetch failed: {ex}")
    return {"ok": True, "applied": len(applied), "skipped": len(skipped)}


@app.get("/api/injuries")
def injuries(severity: str = "high"):
    try:
        payload = ingest_injuries.fetch_injuries()
    except Exception as ex:
        raise HTTPException(502, f"ESPN fetch failed: {ex}")
    by_team = ingest_injuries.parse_injuries(payload, severity=severity)
    teams = sorted(by_team, key=lambda t: -ingest_injuries.team_alert_score(by_team[t]))
    return {"teams": [
        {"team": t,
         "score": ingest_injuries.team_alert_score(by_team[t]),
         "rows": ingest_injuries.sort_by_priority(by_team[t])}
        for t in teams
    ]}


@app.get("/api/teams")
def teams(entry: Optional[str] = None):
    """Every team's remaining schedule with per-week win probabilities.

    Powers the Teams matrix page: rows = teams, columns = weeks, cell =
    opponent + P(win). Probabilities come straight from the probability
    engine (Elo + any stored moneyline overrides) — no MILP involved, so
    this is independent of the projection horizon.

    `entry` marks which teams that entry has already used (burned).
    """
    state = state_mod.load_state()
    used = set()
    if entry is not None:
        if entry not in state["entries"]:
            raise HTTPException(404, f"unknown entry {entry}")
        used = set(state["entries"][entry]["used_teams"])

    legs = _loaded_legs()
    probs = {lid: solver.leg_probs_live(state, lid) for lid in legs}
    records = _records_json()

    sched_map = {t: {} for t in data.TEAMS}
    for lid in legs:
        for away, home in sched.SCHEDULE[lid]["games"]:
            sched_map[away][lid] = {"opp": home, "home": False,
                                    "p": round(probs[lid].get(away, 0), 4)}
            sched_map[home][lid] = {"opp": away, "home": True,
                                    "p": round(probs[lid].get(home, 0), 4)}

    return {
        "weeks": [{"id": lid, "holiday": lid in sched.HOLIDAY_WEEKS} for lid in legs],
        "teams": {
            t: {
                "ou": data.WIN_TOTALS[t][0],
                "fv": round(solver.future_value(t), 2),
                "record": records.get(t),
                "used": t in used,
                "in_tx": t in sched.TXWEEK_POOL,
                "in_xmas": t in sched.XMASWEEK_POOL,
                "schedule": sched_map[t],
            }
            for t in data.TEAMS
        },
    }


@app.get("/api/check")
def check():
    state = state_mod.load_state()
    passes, failures = [], []
    errs = sched.validate()
    if errs:
        failures += [f"schedule: {e}" for e in errs]
    else:
        passes.append("schedule pools match official rules")
    ph = [t for t, (_, p) in data.WIN_TOTALS.items() if p == "PLACEHOLDER"]
    if ph:
        failures.append(f"placeholders remain: {ph}")
    else:
        passes.append("all 32 win totals verified")
    try:
        _, _, meta = _solve(state, dict(DIAL_DEFAULTS))
        if meta["status"] == "Optimal":
            passes.append("solver Optimal")
        else:
            failures.append(f"solver status {meta['status']}")
    except Exception as ex:
        failures.append(f"solver: {ex}")
    for e, ent in state["entries"].items():
        if not ent["alive"]:
            continue
        used = set(ent["used_teams"])
        for hw, pool in [("TXWEEK", sched.TXWEEK_POOL),
                         ("XMASWEEK", sched.XMASWEEK_POOL)]:
            if hw not in ent["picks"] and not (pool - used):
                failures.append(f"entry {e} exhausted {hw}")
    if not any(f.startswith("entry") for f in failures):
        passes.append("holiday rosters viable for every alive entry")
    return {"passes": passes, "failures": failures}
