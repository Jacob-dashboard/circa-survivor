"""
Circa Survivor 2026 — Public Betting Splits (VSiN / DraftKings)
================================================================
Scrapes VSiN's free DraftKings betting-splits page for NFL: per game, the
percentage of BETS (tickets) and percentage of HANDLE (money) on each side
of the spread and moneyline.

Why both numbers matter:
    bets%   = share of tickets  -> where the PUBLIC is
    handle% = share of money    -> where the BIG bets are
When handle% is far above bets% on one side, fewer-but-larger wagers are
taking it — the classic sharp-money signature. Combined with line movement
(ingest_lines.fetch_game_meta open vs close), that's the "where is the money
coming in" feed the Market tab renders.

Reliability notes (be honest with yourself here):
  * This is an HTML scrape of a page VSiN can redesign at any time. The
    parser is defensive: it returns [] rather than raising when the shape
    changes, and the UI displays a "no splits available" state.
  * NFL rows only populate in-season / close to game days. In the offseason
    the page serves other sports; parse_splits() filters to NFL team names
    so offseason returns [] cleanly.
  * VSiN sources these numbers from DraftKings. One book's ticket/handle mix,
    not a market-wide census — directionally useful, not gospel.
"""
import json
import re
import urllib.request

from . import data
from .ingest_schedule import USER_AGENT

VSIN_URL = "https://data.vsin.com/betting-splits/?bookid=dk&view=nfl"

# Full-name fragments -> our abbreviations. VSiN tables use city or nickname
# text; match loosely on nickname since city strings vary ("LA", "N.Y.", etc.)
NICKNAME_TO_ABBR = {
    "Cardinals": "ARI", "Falcons": "ATL", "Ravens": "BAL", "Bills": "BUF",
    "Panthers": "CAR", "Bears": "CHI", "Bengals": "CIN", "Browns": "CLE",
    "Cowboys": "DAL", "Broncos": "DEN", "Lions": "DET", "Packers": "GB",
    "Texans": "HOU", "Colts": "IND", "Jaguars": "JAX", "Chiefs": "KC",
    "Raiders": "LV", "Chargers": "LAC", "Rams": "LAR", "Dolphins": "MIA",
    "Vikings": "MIN", "Patriots": "NE", "Saints": "NO", "Giants": "NYG",
    "Jets": "NYJ", "Eagles": "PHI", "Steelers": "PIT", "49ers": "SF",
    "Seahawks": "SEA", "Buccaneers": "TB", "Titans": "TEN", "Commanders": "WAS",
}


def fetch_splits_html(timeout=20):
    """Raw HTML of the VSiN DK-splits NFL page. Raises on network failure."""
    req = urllib.request.Request(
        VSIN_URL,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _strip_tags(html_fragment):
    return re.sub(r"<[^>]+>", " ", html_fragment)


def parse_splits(html):
    """Best-effort parse of VSiN's splits tables.

    Returns a list of game dicts:
        {"away": abbr, "home": abbr,
         "spread_bets_away": int|None,  "spread_bets_home": int|None,
         "spread_handle_away": int|None,"spread_handle_home": int|None,
         "ml_bets_away": int|None,      "ml_bets_home": int|None,
         "ml_handle_away": int|None,    "ml_handle_home": int|None}

    Empty list when no NFL rows are found (offseason, page redesign, etc.).
    """
    games = []
    # VSiN renders one <tr> per matchup pair or per team row depending on
    # layout era. Strategy: walk <tr> blocks, keep rows containing exactly
    # two known NFL nicknames, and harvest the percent cells in order.
    for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
        row_html = tr_match.group(1)
        text = _strip_tags(row_html)
        teams_found = [(m.start(), abbr) for nick, abbr in NICKNAME_TO_ABBR.items()
                       for m in re.finditer(re.escape(nick), text)]
        if len(teams_found) != 2:
            continue
        teams_found.sort()
        away_abbr, home_abbr = teams_found[0][1], teams_found[1][1]
        pcts = [int(p) for p in re.findall(r"(\d{1,3})%", text) if int(p) <= 100]
        # Expected layouts carry >= 8 percentages per matchup row:
        # spread bets a/h, spread handle a/h, ml bets a/h, ml handle a/h.
        # Some layouts include totals columns too; take the first 8.
        if len(pcts) < 8:
            continue
        games.append({
            "away": away_abbr, "home": home_abbr,
            "spread_bets_away":   pcts[0], "spread_bets_home":   pcts[1],
            "spread_handle_away": pcts[2], "spread_handle_home": pcts[3],
            "ml_bets_away":       pcts[4], "ml_bets_home":       pcts[5],
            "ml_handle_away":     pcts[6], "ml_handle_home":     pcts[7],
        })
    return games


def fetch_splits():
    """One-shot fetch+parse. Returns (games_list, note_str)."""
    try:
        html = fetch_splits_html()
    except Exception as e:
        return [], f"VSiN fetch failed: {e}"
    games = parse_splits(html)
    if not games:
        return [], (
            "No NFL splits rows found on VSiN. Normal in the offseason — the "
            "table populates as game week approaches. If it stays empty "
            "in-season, VSiN likely redesigned the page and the parser in "
            "survivor/ingest_splits.py needs updating."
        )
    return games, f"{len(games)} games parsed from VSiN (DraftKings splits)."


def sharp_signal(bets_pct, handle_pct, threshold=15):
    """Return a short annotation when handle diverges from tickets.

    handle >> bets on a side = fewer, larger wagers = sharp-money signature.
    """
    if bets_pct is None or handle_pct is None:
        return ""
    gap = handle_pct - bets_pct
    if gap >= threshold:
        return "💰 sharp side?"
    if gap <= -threshold:
        return "🎫 public side"
    return ""


if __name__ == "__main__":
    games, note = fetch_splits()
    print(note)
    for g in games:
        print(f"\n{g['away']} @ {g['home']}")
        print(f"  spread: bets {g['spread_bets_away']}/{g['spread_bets_home']}  "
              f"handle {g['spread_handle_away']}/{g['spread_handle_home']}")
        print(f"  ML    : bets {g['ml_bets_away']}/{g['ml_bets_home']}  "
              f"handle {g['ml_handle_away']}/{g['ml_handle_home']}")
