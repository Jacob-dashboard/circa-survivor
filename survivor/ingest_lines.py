"""
Circa Survivor 2026 — Moneyline Ingester
=========================================
Reads DraftKings moneylines from ESPN's scoreboard `odds[0].moneyline` field
(same endpoint family used by ingest_schedule). Writes each game's lines into
state.leg_overrides[leg]["lines"], where survivor.solver picks them up via
solver.leg_probs_live(state, leg_id) and blends them with the Elo model at
the configured market_weight (default 0.85 in state.set_line()).

Provider: DraftKings (ESPN provider.id = 100). One book is enough for the
devig step we run; book-shopping requires the-odds-api.com instead.

Holiday Contest Weeks: the Thanksgiving slate lives inside ESPN's Week 12
(GB@LAR Wed, CHI@DET / PHI@DAL / KC@BUF Thu, DEN@PIT Fri). Christmas lives
inside ESPN's Week 16. The LEG_TO_ESPN_WEEK map below resolves them so
`survivor lines TXWEEK` fetches the right scoreboard call.
"""
from datetime import datetime

from . import schedule as sched
from . import state as state_mod
from .ingest_schedule import _team_abbr, fetch_week

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None

# Contest Week ID -> ESPN week number to fetch.
LEG_TO_ESPN_WEEK = {
    **{f"W{i}": i for i in range(1, 19)},
    "TXWEEK":  12,
    "XMASWEEK": 16,
}


def _parse_odds_int(s):
    """Convert '+170' / '-205' / 170 to int. Return None on anything else."""
    if s is None:
        return None
    try:
        return int(str(s).replace("+", ""))
    except ValueError:
        return None


def _moneyline_from_event(event):
    """Pull (away_abbr, home_abbr, ml_away, ml_home, source_tag) from an ESPN event.

    Falls back to opener if the closer isn't posted yet (early in the week).
    Returns None if either side's odds are missing.
    """
    comp = (event.get("competitions") or [{}])[0]
    home = away = None
    for c in comp.get("competitors", []):
        ab = _team_abbr((c.get("team") or {}).get("abbreviation", ""))
        side = c.get("homeAway")
        if side == "home":
            home = ab
        elif side == "away":
            away = ab
    if not home or not away:
        return None

    odds_list = comp.get("odds") or []
    if not odds_list:
        return None
    ml = (odds_list[0] or {}).get("moneyline") or {}
    ml_h_block = ml.get("home") or {}
    ml_a_block = ml.get("away") or {}

    # Prefer close (latest) over open (initial line).
    def _pick(block):
        close = (block.get("close") or {}).get("odds")
        if close not in (None, ""):
            return close, "close"
        opn = (block.get("open") or {}).get("odds")
        if opn not in (None, ""):
            return opn, "open"
        return None, None

    raw_h, tag_h = _pick(ml_h_block)
    raw_a, tag_a = _pick(ml_a_block)
    ml_h = _parse_odds_int(raw_h)
    ml_a = _parse_odds_int(raw_a)
    if ml_h is None or ml_a is None:
        return None
    source_tag = "close" if (tag_h == "close" and tag_a == "close") else "open"
    return away, home, ml_a, ml_h, source_tag


def ingest_lines_for_leg(state, leg_id, year=2026, dry_run=False):
    """Fetch the ESPN week covering `leg_id` and apply moneylines for every
    game that's listed in SCHEDULE[leg_id]['games'].

    Returns (applied, skipped) where:
      applied = [(away, home, ml_away, ml_home, tag), ...]
      skipped = [(away, home, reason), ...]
    """
    if leg_id not in LEG_TO_ESPN_WEEK:
        raise ValueError(f"Unknown leg {leg_id!r}; expected one of {sorted(LEG_TO_ESPN_WEEK)}")
    if leg_id not in sched.SCHEDULE:
        raise ValueError(f"{leg_id} is not loaded in SCHEDULE.")

    espn_week = LEG_TO_ESPN_WEEK[leg_id]
    events_json = fetch_week(year, espn_week)

    # Build (away, home) -> (ml_a, ml_h, tag) map from the ESPN payload.
    odds_by_game = {}
    for event in events_json.get("events", []):
        parsed = _moneyline_from_event(event)
        if parsed is None:
            continue
        away, home, ml_a, ml_h, tag = parsed
        odds_by_game[(away, home)] = (ml_a, ml_h, tag)

    applied = []
    skipped = []
    for away, home in sched.SCHEDULE[leg_id]["games"]:
        if (away, home) not in odds_by_game:
            skipped.append((away, home, "no DraftKings line posted yet"))
            continue
        ml_a, ml_h, tag = odds_by_game[(away, home)]
        if not dry_run:
            state_mod.set_line(state, leg_id, away, home, ml_a, ml_h)
        applied.append((away, home, ml_a, ml_h, tag))

    if not dry_run and applied:
        state_mod.save_state(state)

    return applied, skipped


# ---------------------------------------------------------------------------
# Display metadata: spreads, totals, kickoff times, opponent lookup
# ---------------------------------------------------------------------------
# These are DISPLAY fields — the solver doesn't read them. They power the
# "This week's picks" panel in the UI so you can see who you're picking
# against and what the market thinks of the matchup.

def format_kickoff_et(iso_str):
    """ '2026-09-10T00:15Z' -> 'Wed Sep 9, 8:15 PM ET'. Falls back to raw."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if _ET is not None:
            dt = dt.astimezone(_ET)
        # %-I (no-pad hour) is platform-dependent; use lstrip('0') instead.
        s = dt.strftime("%a %b %d, %I:%M %p ET").replace(" 0", " ")
        return s
    except Exception:
        return iso_str


def describe_spread_for_pick(pick_team, home, away, spread_home):
    """Return a human-readable spread phrase relative to the pick.

    ESPN's `spread` is home-relative: negative means home favored, positive
    means home is the underdog. We flip the sign if the picked team is away.
    """
    if spread_home is None:
        return None
    spread_for_pick = spread_home if pick_team == home else -spread_home
    if abs(spread_for_pick) < 0.05:
        return f"{pick_team} PK (pick'em)"
    if spread_for_pick < 0:
        return f"{pick_team} {spread_for_pick:.1f} (favorite)"
    return f"{pick_team} +{spread_for_pick:.1f} (UNDERDOG)"


def fetch_game_meta(year, leg_id):
    """Return {(away, home): meta_dict} for every game in the leg.

    meta_dict keys:
      kickoff_iso      str   ISO date from ESPN, UTC
      kickoff_display  str   pretty-printed ET (e.g. 'Sun Sep 13, 1:00 PM ET')
      spread_home      float home-relative spread (negative = home favored)
      spread_text      str   ESPN's pre-formatted text (e.g. 'SEA -3.5')
      total            float over/under
      ml_home          int   close moneyline for home (signed)
      ml_away          int   close moneyline for away (signed)
      status           str   STATUS_SCHEDULED / STATUS_FINAL / etc.
      completed        bool
      venue            str   venue full name + location
    """
    if leg_id not in LEG_TO_ESPN_WEEK or leg_id not in sched.SCHEDULE:
        return {}
    events_json = fetch_week(year, LEG_TO_ESPN_WEEK[leg_id])
    out = {}
    for event in events_json.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        home = away = None
        for c in comp.get("competitors", []):
            ab = _team_abbr((c.get("team") or {}).get("abbreviation", ""))
            if c.get("homeAway") == "home":
                home = ab
            elif c.get("homeAway") == "away":
                away = ab
        if not home or not away:
            continue

        status_type = (comp.get("status") or {}).get("type") or {}
        venue = comp.get("venue") or {}
        addr = venue.get("address") or {}
        venue_str = venue.get("fullName") or ""
        if addr:
            city = (addr.get("city") or "").strip()
            country = (addr.get("country") or "").strip()
            tag = ", ".join(p for p in (city, country) if p)
            if tag:
                venue_str = f"{venue_str} ({tag})" if venue_str else tag

        meta = {
            "kickoff_iso":     event.get("date", ""),
            "kickoff_display": format_kickoff_et(event.get("date", "")),
            "spread_home":     None,
            "spread_home_open": None,
            "spread_text":     None,
            "total":           None,
            "total_open":      None,
            "ml_home":         None,
            "ml_away":         None,
            "ml_home_open":    None,
            "ml_away_open":    None,
            "status":          status_type.get("description") or "",
            "completed":       bool(status_type.get("completed")),
            "venue":           venue_str,
        }

        odds_list = comp.get("odds") or []
        if odds_list:
            o = odds_list[0]
            meta["spread_home"] = o.get("spread")
            meta["spread_text"] = o.get("details")
            meta["total"] = o.get("overUnder")
            ml = o.get("moneyline") or {}
            ml_h = ml.get("home") or {}
            ml_a = ml.get("away") or {}
            meta["ml_home"] = _parse_odds_int((ml_h.get("close") or {}).get("odds"))
            meta["ml_away"] = _parse_odds_int((ml_a.get("close") or {}).get("odds"))
            meta["ml_home_open"] = _parse_odds_int((ml_h.get("open") or {}).get("odds"))
            meta["ml_away_open"] = _parse_odds_int((ml_a.get("open") or {}).get("odds"))
            # Open spread lives under pointSpread.home.open.line (e.g. '-3.5')
            ps_home_open = (((o.get("pointSpread") or {}).get("home") or {})
                            .get("open") or {}).get("line")
            try:
                meta["spread_home_open"] = float(ps_home_open) if ps_home_open not in (None, "") else None
            except ValueError:
                meta["spread_home_open"] = None
            # Open total: total.over.open.line like 'o44.5'
            t_open = (((o.get("total") or {}).get("over") or {})
                      .get("open") or {}).get("line")
            if t_open:
                try:
                    meta["total_open"] = float(str(t_open).lstrip("ou"))
                except ValueError:
                    pass

        out[(away, home)] = meta
    return out


def game_for_team(meta_by_pair, team):
    """Find the (away, home, meta) tuple in meta_by_pair where team plays.

    Returns None if the team isn't in this leg.
    """
    for (away, home), meta in meta_by_pair.items():
        if team == away or team == home:
            return away, home, meta
    return None
