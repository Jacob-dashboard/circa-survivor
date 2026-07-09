"""
Circa Survivor 2026 — Injury Surfacer
======================================
Reads ESPN's NFL injuries endpoint and surfaces the high-impact rows. This
module is INTENTIONALLY read-only: it does NOT modify BASE_ELO or call
state.adjust_strength(). The translation from "Mahomes Questionable" to a
numeric Elo delta is a judgment call that no API can make for us.

What it does:
  - Hits `…/nfl/injuries` (no auth, free).
  - Filters by severity (default: high — Out / Doubtful / IR / PUP / Suspended).
  - Optionally filters by team abbreviation.
  - Sorts within each team so QBs and other key positions surface first.

Workflow:
  1. `python -m survivor injuries`  — full-league high-severity sweep.
  2. Eyeball the QB / OT / EDGE / CB rows.
  3. If something matters: `python -m survivor nudge KC -25 --note "Mahomes Out"`.
"""
import json
import urllib.request

from .ingest_schedule import USER_AGENT, _team_abbr

INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"

HIGH_SEVERITY = {
    "Out", "Doubtful", "Injured Reserve",
    "Physically Unable to Perform", "Suspended",
}
MEDIUM_SEVERITY = {"Questionable"}

# Positions whose absence moves the line meaningfully. QB is its own tier.
QB_POS = {"QB"}
KEY_POS = {"LT", "RT", "WR", "TE", "CB", "EDGE", "DE", "DT", "LB", "RB", "C", "OL", "S"}

_SEVERITY_RANK = {
    "Out": 0, "Doubtful": 1, "Injured Reserve": 2,
    "Physically Unable to Perform": 3, "Suspended": 4, "Questionable": 5,
}


def fetch_injuries():
    """One-shot fetch of the full league injury report."""
    req = urllib.request.Request(INJURIES_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"ESPN injuries fetch failed: {e}") from e


def parse_injuries(payload, severity="high"):
    """Return {team_abbr: [{name, position, status, type, detail}, ...]}.

    severity='high' -> Out/Doubtful/IR/PUP/Suspended only (default).
    severity='all'  -> include Questionable too.
    """
    threshold = HIGH_SEVERITY if severity == "high" else (HIGH_SEVERITY | MEDIUM_SEVERITY)
    by_team = {}
    for team in payload.get("injuries", []):
        # ESPN's injuries payload puts the team's abbreviation on each athlete's
        # nested team object, NOT on the outer team entry (which carries only
        # id/displayName/injuries). Pull from the first injury's athlete; fall
        # back to top-level fields just in case ESPN changes the shape.
        injuries_list = team.get("injuries") or []
        abbr = None
        if injuries_list:
            athlete_team = ((injuries_list[0].get("athlete") or {}).get("team")) or {}
            abbr = athlete_team.get("abbreviation")
        if not abbr:
            abbr = team.get("abbreviation") or (team.get("team") or {}).get("abbreviation")
        if not abbr:
            continue
        abbr = _team_abbr(abbr)
        rows = []
        for inj in team.get("injuries", []):
            status = inj.get("status") or ""
            if status not in threshold:
                continue
            athlete = inj.get("athlete") or {}
            pos = ((athlete.get("position") or {}).get("abbreviation")) or ""
            name = athlete.get("displayName") or "?"
            inj_type = (inj.get("type") or {}).get("description") or ""
            detail = (inj.get("details") or {}).get("detail") or ""
            rows.append({
                "name": name, "position": pos, "status": status,
                "type": inj_type, "detail": detail,
            })
        if rows:
            by_team[abbr] = rows
    return by_team


def sort_by_priority(rows):
    """QBs first, then other key positions, then within each tier by severity."""
    def keyfn(r):
        tier = 0 if r["position"] in QB_POS else (1 if r["position"] in KEY_POS else 2)
        sev = _SEVERITY_RANK.get(r["status"], 9)
        return (tier, sev, r["name"])
    return sorted(rows, key=keyfn)


def team_alert_score(rows):
    """Heuristic: how 'newsworthy' is this team's injury list?

    Used to sort teams when scanning the whole league. QB Out is the loudest
    single signal; everything else is much quieter.
    """
    score = 0
    for r in rows:
        if r["position"] in QB_POS and r["status"] in ("Out", "Doubtful", "Suspended"):
            score += 100
        elif r["position"] in QB_POS:
            score += 30  # QB on IR / PUP
        elif r["position"] in KEY_POS and r["status"] == "Out":
            score += 5
        else:
            score += 1
    return score
