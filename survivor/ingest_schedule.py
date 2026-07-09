"""
Circa Survivor 2026 — ESPN Schedule Ingester
============================================
Pulls the full 2026 NFL regular-season schedule from ESPN's public scoreboard
endpoint and merges it into survivor/schedule.py.

This is a PERSONAL WEEKLY TOOL, not a production service. The endpoint
    https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
is unofficial — ESPN can change or remove it without notice. No auth, no SLA.

Safety contract for write_to_schedule_module():
  * NEVER overwrite TXWEEK or XMASWEEK; both are manually verified against the
    official rules PDF and are the terminal node of the portfolio plan.
  * NEVER reset NEUTRAL_SITE_GAMES; the ingester only surfaces CANDIDATES, never
    auto-classifies. Human curates.
  * LEG_ORDER is rebuilt with holiday weeks placed chronologically by the actual
    dates ESPN returns.
  * Refuse to write if any fetched team abbreviation isn't in data.BASE_ELO.
  * dry_run=True writes to survivor/schedule.py.proposed for review.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from . import data
from . import schedule as sched_mod

ESPN_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    "?dates={year}&seasontype=2&week={week}"
)
USER_AGENT = "circa-survivor-tool/1.0"
SCHEDULE_PATH = os.path.join(os.path.dirname(__file__), "schedule.py")

# Map ESPN team abbreviations to ours where they disagree.
# Verify against data.BASE_ELO on first run; the brief flagged LV as the one
# to watch (ESPN uses LV; we use LV; we expect a no-op).
ESPN_ABBR_OVERRIDES: dict = {
    # ESPN uses WSH for Washington; our BASE_ELO key is WAS.
    "WSH": "WAS",
    # LV (Raiders) is shared — no override needed; verified on first run.
}

# Side-channel meta from the most recent build_schedule_dict() call. The
# __main__ block reads this; write_to_schedule_module also uses it for date
# information when placing TXWEEK/XMASWEEK in LEG_ORDER.
_LAST_FETCH_META: dict = {
    "dates": {},                 # wid -> [iso_date, ...]
    "neutral_candidates": [],    # [(wid, away, home, venue_str), ...]
    "unknown_abbrs": [],         # sorted list of unmapped abbreviations
}


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_week(year: int, week: int) -> dict:
    """Hit ESPN scoreboard for one (year, week). Raises on network failure."""
    url = ESPN_URL.format(year=year, week=week)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"ESPN fetch failed for {year} week {week}: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ESPN returned non-JSON for {year} week {week}: {e}") from e


def _team_abbr(abbr: str) -> str:
    return ESPN_ABBR_OVERRIDES.get(abbr, abbr)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_games(events_json: dict) -> list:
    """Pull (away, home, date, neutral_hint, venue) for each event.

    neutral_hint = True when venue.country is non-USA. The home-city heuristic
    in the brief is intentionally omitted because we don't carry a team->city
    table, and the country signal alone catches all international games.
    Anything ambiguous is for the human to classify.
    """
    games = []
    for event in events_json.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        comp = comps[0]
        home_team = away_team = None
        for c in comp.get("competitors", []):
            team = (c.get("team") or {}).get("abbreviation")
            if not team:
                continue
            abbr = _team_abbr(team)
            if c.get("homeAway") == "home":
                home_team = abbr
            elif c.get("homeAway") == "away":
                away_team = abbr
        if not home_team or not away_team:
            continue
        venue = comp.get("venue") or {}
        addr = venue.get("address") or {}
        country = (addr.get("country") or "").strip()
        city = (addr.get("city") or "").strip()
        state = (addr.get("state") or "").strip()
        is_international = bool(country) and country.upper() not in ("USA", "US", "UNITED STATES")
        venue_str = f"{venue.get('fullName', '')} ({city}{', '+state if state else ''}{', '+country if country else ''})"
        games.append({
            "away": away_team,
            "home": home_team,
            "date": event.get("date", ""),
            "neutral_hint": is_international,
            "venue": venue_str.strip(),
        })
    games.sort(key=lambda g: g["date"])
    return games


# ---------------------------------------------------------------------------
# Build the SCHEDULE-shape dict
# ---------------------------------------------------------------------------

def build_schedule_dict(year: int = 2026) -> dict:
    """Pull all 18 weeks and return {W1..W18: {label, verified, games}}.

    Stashes per-week dates, neutral-site candidates, and any unknown
    team abbreviations into module-level _LAST_FETCH_META for inspection.
    """
    schedule_dict = {}
    dates_by_week = {}
    neutral_candidates = []
    unknown = set()

    for week in range(1, 19):
        events = fetch_week(year, week)
        games = parse_games(events)
        wid = f"W{week}"
        for g in games:
            for t in (g["away"], g["home"]):
                if t not in data.BASE_ELO:
                    unknown.add(t)
        schedule_dict[wid] = {
            "label": f"Week {week}",
            "verified": True,
            "games": [(g["away"], g["home"]) for g in games],
        }
        dates_by_week[wid] = [g["date"] for g in games]
        for g in games:
            if g["neutral_hint"]:
                neutral_candidates.append((wid, g["away"], g["home"], g["venue"]))

    _LAST_FETCH_META["dates"] = dates_by_week
    _LAST_FETCH_META["neutral_candidates"] = neutral_candidates
    _LAST_FETCH_META["unknown_abbrs"] = sorted(unknown)
    return schedule_dict


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------

_FILE_TEMPLATE = '''"""
Circa Survivor 2026 — Schedule Layer (CORRECTED per official rules)
===================================================================
A CONTEST WEEK is a set of games from which an entry picks exactly ONE winning
team. There are up to 20 Contest Weeks total:
  - 18 standard weeks (NFL Weeks 1-18)
  - "TXWEEK"  = Thanksgiving Week (Wed Nov 25 + Thu Nov 26 + Fri Nov 27), ONE pick
  - "XMASWEEK" = Christmas Week (Thu Dec 24 + Fri Dec 25), ONE pick

W1-W18 ingested from ESPN by survivor/ingest_schedule.py (regenerated on
every successful run). The two holiday Contest Weeks are MANUALLY VERIFIED
against the official rules PDF (Rev. 5/16/2026, Rules 7-9) and the ingester
preserves them untouched.

The "team pool" for a week = every team playing in that week. For holiday weeks
the rules name the pools explicitly; we assert our game list matches them.

Each game = (away, home). A pick is a team; it survives if it WINS (tie = loss).
"""

# ---------------------------------------------------------------------------
# Official holiday team pools (Rules 8 & 9) -- used to VALIDATE game lists.
# ---------------------------------------------------------------------------
TXWEEK_POOL = {{"GB", "LAR", "CHI", "DET", "PHI", "DAL", "KC", "BUF", "DEN", "PIT"}}
XMASWEEK_POOL = {{"HOU", "PHI", "GB", "CHI", "BUF", "DEN", "LAR", "SEA"}}

SCHEDULE = {{
{schedule_body}
}}

# Neutral-site games (international) -- zero out HFA. Manually curated.
# survivor/ingest_schedule.py surfaces candidates (anything ESPN tags with a
# non-USA venue country) but DOES NOT auto-populate this dict. Eyeball the
# candidate list from the ingester run and add entries here by hand.
NEUTRAL_SITE_GAMES = {{
{neutral_body}
}}

# The two holiday Contest Weeks = the terminal node the portfolio back-plans to.
HOLIDAY_WEEKS = ["TXWEEK", "XMASWEEK"]

# Teams appearing in BOTH holiday pools -- using one in TXWEEK removes it from XMAS.
HOLIDAY_OVERLAP = TXWEEK_POOL & XMASWEEK_POOL  # {{GB,LAR,CHI,BUF,DEN,PHI}}

# Chronological ordering, with holiday Contest Weeks slotted in by date.
LEG_ORDER = {leg_order_body}


def teams_in_week(week_id):
    """All teams playing in a Contest Week = its selectable pool."""
    teams = set()
    for away, home in SCHEDULE[week_id]["games"]:
        teams.add(away); teams.add(home)
    return teams


def validate():
    """Assert holiday game lists match the official rule pools. Raises if not."""
    errs = []
    if "TXWEEK" in SCHEDULE:
        got = teams_in_week("TXWEEK")
        if got != TXWEEK_POOL:
            errs.append(f"TXWEEK pool mismatch: extra={{{{got-TXWEEK_POOL}}}}, missing={{{{TXWEEK_POOL-got}}}}")
    if "XMASWEEK" in SCHEDULE:
        got = teams_in_week("XMASWEEK")
        if got != XMASWEEK_POOL:
            errs.append(f"XMASWEEK pool mismatch: extra={{{{got-XMASWEEK_POOL}}}}, missing={{{{XMASWEEK_POOL-got}}}}")
    return errs


if __name__ == "__main__":
    errs = validate()
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
    else:
        print("Holiday pools match official rules. OK.")
    print("\\nTXWEEK pool   :", sorted(teams_in_week("TXWEEK")))
    print("XMASWEEK pool :", sorted(teams_in_week("XMASWEEK")))
    print("Overlap (both):", sorted(HOLIDAY_OVERLAP))
'''


def _format_games_block(games, indent=12):
    pad = " " * indent
    return "\n".join(f"{pad}({away!r}, {home!r})," for away, home in games)


def _format_week_entry(wid, week_data, marker):
    games_block = _format_games_block(week_data["games"], indent=12)
    if not games_block:
        games_block = "            # (no games)"
    return (
        f"    # {marker}\n"
        f"    {wid!r}: {{\n"
        f"        \"label\": {week_data['label']!r},\n"
        f"        \"verified\": {week_data['verified']},\n"
        f"        \"games\": [\n"
        f"{games_block}\n"
        f"        ],\n"
        f"    }},"
    )


def _format_schedule_body(schedule_dict, leg_order):
    blocks = []
    for wid in leg_order:
        if wid not in schedule_dict:
            continue
        is_holiday = wid in ("TXWEEK", "XMASWEEK")
        marker = (
            "PRESERVED -- manually verified, do not auto-edit"
            if is_holiday
            else "INGESTED from ESPN"
        )
        blocks.append(_format_week_entry(wid, schedule_dict[wid], marker))
    return "\n".join(blocks)


def _format_neutral_block(neutral_dict):
    if not neutral_dict:
        return "    # No neutral-site games confirmed yet. Candidates from the\n    # ingester run go here once a human confirms them.\n    # ('SF', 'LAR'): 'Week 1 Australia',"
    lines = []
    for (a, h), desc in neutral_dict.items():
        lines.append(f"    ({a!r}, {h!r}): {desc!r},")
    return "\n".join(lines)


def _format_leg_order(leg_order):
    items = ", ".join(repr(x) for x in leg_order)
    return f"[{items}]"


# ---------------------------------------------------------------------------
# Chronological LEG_ORDER
# ---------------------------------------------------------------------------

def _iso(d: str):
    try:
        return datetime.fromisoformat(d.replace("Z", "+00:00"))
    except Exception:
        return None


def _compute_leg_order(schedule_dict, week_dates):
    """Return (leg_order, tx_target_week, xmas_target_week).

    Holiday Contest Weeks are placed IMMEDIATELY BEFORE the ESPN week whose
    date range contains Thanksgiving Thursday (Nov 26, 2026) for TXWEEK and
    Christmas Day (Dec 25, 2026) for XMASWEEK. Placing them before the
    overlapping ESPN week reflects the contest deadline: TXWEEK picks lock
    when the Wed/Thu/Fri slate kicks off, which precedes that week's
    Sun/Mon games.
    """
    tx_week = None
    xmas_week = None
    for i in range(1, 19):
        wid = f"W{i}"
        for d in week_dates.get(wid, []):
            dt = _iso(d)
            if dt is None:
                continue
            if dt.month == 11 and dt.day == 26 and tx_week is None:
                tx_week = wid
            if dt.month == 12 and dt.day == 25 and xmas_week is None:
                xmas_week = wid

    order = []
    for i in range(1, 19):
        wid = f"W{i}"
        if wid == tx_week:
            order.append("TXWEEK")
        if wid == xmas_week:
            order.append("XMASWEEK")
        order.append(wid)
    return order, tx_week, xmas_week


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_to_schedule_module(schedule_dict: dict, dry_run: bool = True) -> str:
    """Merge ingested W1..W18 with preserved holiday weeks and write.

    Returns the path written. dry_run=True -> schedule.py.proposed.
    """
    # Carry holiday weeks from the existing module verbatim. This is the only
    # source-of-truth move; the docstring drilled it in red.
    existing = sched_mod.SCHEDULE
    if "TXWEEK" in existing:
        schedule_dict["TXWEEK"] = existing["TXWEEK"]
    if "XMASWEEK" in existing:
        schedule_dict["XMASWEEK"] = existing["XMASWEEK"]

    # Refuse to write if ESPN handed us a team we can't price.
    unknown = set()
    for wd in schedule_dict.values():
        for away, home in wd["games"]:
            for t in (away, home):
                if t not in data.BASE_ELO:
                    unknown.add(t)
    if unknown:
        raise RuntimeError(
            f"Refusing to write: unknown team abbreviations {sorted(unknown)}. "
            "Add to data.BASE_ELO or ESPN_ABBR_OVERRIDES."
        )

    week_dates = _LAST_FETCH_META.get("dates", {})
    leg_order, tx_target, xmas_target = _compute_leg_order(schedule_dict, week_dates)

    content = _FILE_TEMPLATE.format(
        schedule_body=_format_schedule_body(schedule_dict, leg_order),
        neutral_body=_format_neutral_block(sched_mod.NEUTRAL_SITE_GAMES),
        leg_order_body=_format_leg_order(leg_order),
    )

    out_path = SCHEDULE_PATH + (".proposed" if dry_run else "")
    with open(out_path, "w") as f:
        f.write(content)
    return out_path


# ---------------------------------------------------------------------------
# In-memory validation (the proposed module isn't importable while it sits
# next to the live one; just replicate the rule check on the dict).
# ---------------------------------------------------------------------------

def validate_against(schedule_dict: dict) -> list:
    errs = []
    if "TXWEEK" in schedule_dict:
        got = set()
        for a, h in schedule_dict["TXWEEK"]["games"]:
            got.add(a); got.add(h)
        if got != sched_mod.TXWEEK_POOL:
            errs.append(f"TXWEEK pool mismatch: extra={got-sched_mod.TXWEEK_POOL}, missing={sched_mod.TXWEEK_POOL-got}")
    if "XMASWEEK" in schedule_dict:
        got = set()
        for a, h in schedule_dict["XMASWEEK"]["games"]:
            got.add(a); got.add(h)
        if got != sched_mod.XMASWEEK_POOL:
            errs.append(f"XMASWEEK pool mismatch: extra={got-sched_mod.XMASWEEK_POOL}, missing={sched_mod.XMASWEEK_POOL-got}")
    return errs


# ---------------------------------------------------------------------------
# __main__: full flow in dry-run
# ---------------------------------------------------------------------------

def _run(year: int = 2026, dry_run: bool = True):
    print(f"Fetching ESPN schedule for {year}…")
    schedule_dict = build_schedule_dict(year)

    # Snapshot before merging holiday weeks (write_to_schedule_module adds them).
    espn_only = dict(schedule_dict)

    print()
    print("=== Games per week (ESPN) ===")
    total = 0
    for i in range(1, 19):
        wid = f"W{i}"
        n = len(espn_only[wid]["games"])
        total += n
        print(f"  {wid:<4s} {n:>2d} games")
    print(f"  TOTAL: {total} games  (expected 272 for full regular season)")

    unknown = _LAST_FETCH_META["unknown_abbrs"]
    print()
    if unknown:
        print("=== UNKNOWN TEAM ABBREVIATIONS (will block write) ===")
        for a in unknown:
            print(f"  - {a}")
    else:
        print("=== Team abbreviations: all map cleanly to BASE_ELO. ===")

    neutral = _LAST_FETCH_META["neutral_candidates"]
    print()
    if neutral:
        print(f"=== Neutral-site candidates ({len(neutral)}; for human review) ===")
        for wid, a, h, venue in neutral:
            print(f"  {wid}  {a} @ {h}  -- {venue}")
    else:
        print("=== Neutral-site candidates: none flagged by ESPN venue.country. ===")

    # Diff current vs proposed keys.
    current_keys = set(sched_mod.SCHEDULE.keys())
    proposed_keys = set(schedule_dict.keys()) | {"TXWEEK", "XMASWEEK"}
    added = sorted(proposed_keys - current_keys)
    removed = sorted(current_keys - proposed_keys)
    overwritten = sorted(k for k in current_keys & proposed_keys if k not in ("TXWEEK", "XMASWEEK"))
    print()
    print("=== Schedule key diff ===")
    print(f"  added       : {added}")
    print(f"  removed     : {removed}")
    print(f"  overwritten : {overwritten}  (W1 stub replaced by full ESPN slate)")
    print(f"  preserved   : ['TXWEEK', 'XMASWEEK']")

    out_path = write_to_schedule_module(schedule_dict, dry_run=dry_run)
    print()
    print(f"Wrote: {out_path}  (dry_run={dry_run})")

    # Pull LEG_ORDER out of the freshly computed value for display.
    leg_order, tx_target, xmas_target = _compute_leg_order(
        schedule_dict, _LAST_FETCH_META["dates"]
    )
    print()
    print("=== Proposed LEG_ORDER ===")
    print(f"  TXWEEK placed before {tx_target!r}   (ESPN week containing Nov 26)")
    print(f"  XMASWEEK placed before {xmas_target!r} (ESPN week containing Dec 25)")
    print(f"  order: {leg_order}")

    errs = validate_against(schedule_dict)
    print()
    if errs:
        print("VALIDATION AGAINST POOLS: FAILED")
        for e in errs:
            print(f"  - {e}")
    else:
        print("VALIDATION AGAINST POOLS: OK (holiday game lists match official pools).")


if __name__ == "__main__":
    import sys
    dry = "--commit" not in sys.argv
    _run(year=2026, dry_run=dry)
