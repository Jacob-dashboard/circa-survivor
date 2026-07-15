"""
Circa Survivor 2026 — Power Rankings (ESPN FPI)
================================================
Pulls ESPN's Football Power Index — a live, professionally-maintained team
rating (points better/worse than an average team on a neutral field),
updated daily in season.

Where it fits the model: FPI is a THIRD strength signal layered into the
rating stack, blended inside state.current_elo():

    our_rating = BASE_ELO (June win-total anchor)
               + elo_adjustments (results Elo + manual nudges)
    final      = (1 - w) * our_rating + w * (1500 + FPI_points * 25)

25 Elo per FPI point matches the model's existing scale (1 win-total point
= 25 Elo; 1 spread point ~ 25 Elo). The blend weight lives in state
("power_rankings"."weight", default 0.35) so every surface — solver, Teams
matrix, holiday reservations, what-ifs — prices the blend with zero extra
plumbing. FPI catches what score-only Elo can't see quickly (efficiency vs
record, injury context), while the results-Elo keeps learning on its own.

Manual "Ingest FPI" action (Tools page): FPI moves daily, but weekly-ish
refreshes are plenty for survivor decisions.
"""
import json
import urllib.request

from . import data
from .ingest_schedule import ESPN_ABBR_OVERRIDES

FPI_URL = ("https://site.web.api.espn.com/apis/fitt/v3/sports/football/nfl/"
           "powerindex?region=us&lang=en&limit=40")

ELO_PER_FPI_POINT = 25.0
DEFAULT_WEIGHT = 0.35


def fetch_fpi():
    """Return ({abbr: fpi_points}, last_updated_iso). Raises on failure."""
    req = urllib.request.Request(FPI_URL, headers={"User-Agent": "circa-survivor-tool/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode("utf-8"))

    out = {}
    for entry in payload.get("teams", []):
        abbr = (entry.get("team") or {}).get("abbreviation")
        if not abbr:
            continue
        abbr = ESPN_ABBR_OVERRIDES.get(abbr, abbr)
        fpi_val = None
        for cat in entry.get("categories", []):
            if cat.get("name") == "fpi":
                names = None  # values order is defined by top-level categories
                vals = cat.get("values") or []
                if vals:
                    fpi_val = vals[0]  # index 0 = "fpi" per the category schema
                break
        if fpi_val is not None and abbr in data.BASE_ELO:
            out[abbr] = round(float(fpi_val), 2)
    return out, payload.get("lastUpdated")


def ingest_power(state, weight=None):
    """Fetch FPI into state['power_rankings']. Caller saves state.

    Keeps any previously chosen blend weight unless a new one is given.
    Returns the stored block."""
    fpi, updated = fetch_fpi()
    if len(fpi) < 28:
        raise RuntimeError(f"FPI fetch returned only {len(fpi)} teams — refusing to store")
    prev = state.get("power_rankings") or {}
    state["power_rankings"] = {
        "fpi": fpi,
        "fetched": updated,
        "weight": (weight if weight is not None
                   else prev.get("weight", DEFAULT_WEIGHT)),
    }
    return state["power_rankings"]
