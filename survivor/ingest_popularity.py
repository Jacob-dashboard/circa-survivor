"""
Circa Survivor 2026 — Pick Popularity (SurvivorGrid)
=====================================================
Scrapes SurvivorGrid's public NFL survivor grid for the P% column: the share
of the survivor field currently picking each team this week.

Why this matters — real contrarian edge: until now the solver's contrarian
term faded a PROXY (win-prob rank). Real field data is the actual thing:
when 34% of the pool is on JAX and JAX loses, everyone still on JAX dies and
you gain enormous ground by having been elsewhere. That leverage is only
visible with true pick percentages. Ingested popularity replaces the proxy
in solver's `pop` term for whichever leg it's stored under.

Reliability: HTML scrape of SurvivorGrid's table (columns EV · W% · P% ·
Team). It fails soft — returns {} on any parse problem — and only stores
when >= 28 teams parse, so a page redesign degrades to the old proxy rather
than feeding garbage. P% is meaningful for the CURRENT pick week; future
weeks have no field yet, so ingest applies to one leg at a time.
"""
import re
import urllib.request

from . import data
from .ingest_schedule import ESPN_ABBR_OVERRIDES

SG_URL = "https://www.survivorgrid.com/"


def fetch_popularity():
    """Return {team_abbr: pick_fraction} (0..1) from SurvivorGrid. {} on failure."""
    try:
        req = urllib.request.Request(
            SG_URL, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return {}

    tbody = re.search(r"<tbody.*?</tbody>", body, re.DOTALL)
    if not tbody:
        return {}
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(0), re.DOTALL)

    out = {}
    for row in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)]
        if len(cells) < 4:
            continue
        # columns: EV, W%, P%, Team, ...
        p_raw, team_cell = cells[2], cells[3]
        m = re.search(r"\b([A-Z]{2,3})\b", team_cell)
        if not m:
            continue
        abbr = ESPN_ABBR_OVERRIDES.get(m.group(1), m.group(1))
        if abbr not in data.BASE_ELO:
            continue
        pm = re.search(r"(\d{1,3}(?:\.\d)?)", p_raw)
        if not pm:
            continue
        frac = float(pm.group(1)) / 100.0
        out[abbr] = round(min(1.0, max(0.0, frac)), 4)
    return out


def ingest_popularity(state, leg):
    """Fetch SurvivorGrid P% and store it under state['pick_popularity'][leg].
    Caller saves state. Raises if too few teams parse (keeps stale/proxy)."""
    pop = fetch_popularity()
    if len(pop) < 28:
        raise RuntimeError(f"SurvivorGrid returned only {len(pop)} teams — refusing to store")
    state.setdefault("pick_popularity", {})[leg] = pop
    return pop
