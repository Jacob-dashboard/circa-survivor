"""
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
TXWEEK_POOL = {"GB", "LAR", "CHI", "DET", "PHI", "DAL", "KC", "BUF", "DEN", "PIT"}
XMASWEEK_POOL = {"HOU", "PHI", "GB", "CHI", "BUF", "DEN", "LAR", "SEA"}

SCHEDULE = {
    # INGESTED from ESPN
    'W1': {
        "label": 'Week 1',
        "verified": True,
        "games": [
            ('NE', 'SEA'),
            ('SF', 'LAR'),
            ('TB', 'CIN'),
            ('NO', 'DET'),
            ('NYJ', 'TEN'),
            ('BAL', 'IND'),
            ('ATL', 'PIT'),
            ('CHI', 'CAR'),
            ('CLE', 'JAX'),
            ('BUF', 'HOU'),
            ('MIA', 'LV'),
            ('GB', 'MIN'),
            ('WAS', 'PHI'),
            ('ARI', 'LAC'),
            ('DAL', 'NYG'),
            ('DEN', 'KC'),
        ],
    },
    # INGESTED from ESPN
    'W2': {
        "label": 'Week 2',
        "verified": True,
        "games": [
            ('DET', 'BUF'),
            ('CAR', 'ATL'),
            ('MIN', 'CHI'),
            ('PHI', 'TEN'),
            ('PIT', 'NE'),
            ('GB', 'NYJ'),
            ('CLE', 'TB'),
            ('NO', 'BAL'),
            ('CIN', 'HOU'),
            ('JAX', 'DEN'),
            ('LV', 'LAC'),
            ('WAS', 'DAL'),
            ('SEA', 'ARI'),
            ('MIA', 'SF'),
            ('IND', 'KC'),
            ('NYG', 'LAR'),
        ],
    },
    # INGESTED from ESPN
    'W3': {
        "label": 'Week 3',
        "verified": True,
        "games": [
            ('ATL', 'GB'),
            ('LAC', 'BUF'),
            ('CAR', 'CLE'),
            ('NYJ', 'DET'),
            ('HOU', 'IND'),
            ('KC', 'MIA'),
            ('TEN', 'NYG'),
            ('CIN', 'PIT'),
            ('SEA', 'WAS'),
            ('NE', 'JAX'),
            ('ARI', 'SF'),
            ('MIN', 'TB'),
            ('BAL', 'DAL'),
            ('LV', 'NO'),
            ('LAR', 'DEN'),
            ('PHI', 'CHI'),
        ],
    },
    # INGESTED from ESPN
    'W4': {
        "label": 'Week 4',
        "verified": True,
        "games": [
            ('PIT', 'CLE'),
            ('IND', 'WAS'),
            ('NE', 'BUF'),
            ('NYJ', 'CHI'),
            ('JAX', 'CIN'),
            ('ARI', 'NYG'),
            ('LAR', 'PHI'),
            ('GB', 'TB'),
            ('TEN', 'BAL'),
            ('DAL', 'HOU'),
            ('MIA', 'MIN'),
            ('KC', 'LV'),
            ('DEN', 'SF'),
            ('LAC', 'SEA'),
            ('DET', 'CAR'),
            ('ATL', 'NO'),
        ],
    },
    # INGESTED from ESPN
    'W5': {
        "label": 'Week 5',
        "verified": True,
        "games": [
            ('TB', 'DAL'),
            ('PHI', 'JAX'),
            ('HOU', 'TEN'),
            ('CIN', 'MIA'),
            ('LV', 'NE'),
            ('MIN', 'NO'),
            ('CLE', 'NYJ'),
            ('IND', 'PIT'),
            ('NYG', 'WAS'),
            ('DEN', 'LAC'),
            ('CHI', 'GB'),
            ('DET', 'ARI'),
            ('SF', 'SEA'),
            ('BAL', 'ATL'),
            ('BUF', 'LAR'),
        ],
    },
    # INGESTED from ESPN
    'W6': {
        "label": 'Week 6',
        "verified": True,
        "games": [
            ('SEA', 'DEN'),
            ('HOU', 'JAX'),
            ('CHI', 'ATL'),
            ('BAL', 'CLE'),
            ('TEN', 'IND'),
            ('NYJ', 'NE'),
            ('NO', 'NYG'),
            ('CAR', 'PHI'),
            ('PIT', 'TB'),
            ('ARI', 'LAR'),
            ('LAC', 'KC'),
            ('BUF', 'LV'),
            ('DAL', 'GB'),
            ('WAS', 'SF'),
        ],
    },
    # INGESTED from ESPN
    'W7': {
        "label": 'Week 7',
        "verified": True,
        "games": [
            ('NE', 'CHI'),
            ('PIT', 'NO'),
            ('SF', 'ATL'),
            ('CLE', 'TEN'),
            ('IND', 'MIN'),
            ('MIA', 'NYJ'),
            ('TB', 'CAR'),
            ('CIN', 'BAL'),
            ('NYG', 'HOU'),
            ('DEN', 'ARI'),
            ('GB', 'DET'),
            ('LAR', 'LV'),
            ('KC', 'SEA'),
            ('DAL', 'PHI'),
        ],
    },
    # INGESTED from ESPN
    'W8': {
        "label": 'Week 8',
        "verified": True,
        "games": [
            ('CAR', 'GB'),
            ('BAL', 'BUF'),
            ('TEN', 'CIN'),
            ('ARI', 'DAL'),
            ('MIN', 'DET'),
            ('LV', 'NYJ'),
            ('CLE', 'PIT'),
            ('ATL', 'TB'),
            ('IND', 'JAX'),
            ('LAC', 'LAR'),
            ('KC', 'DEN'),
            ('NE', 'MIA'),
            ('PHI', 'WAS'),
            ('CHI', 'SEA'),
        ],
    },
    # INGESTED from ESPN
    'W9': {
        "label": 'Week 9',
        "verified": True,
        "games": [
            ('JAX', 'BAL'),
            ('CIN', 'ATL'),
            ('DAL', 'IND'),
            ('NYJ', 'KC'),
            ('DET', 'MIA'),
            ('CLE', 'NO'),
            ('NYG', 'PHI'),
            ('LAR', 'WAS'),
            ('DEN', 'CAR'),
            ('HOU', 'LAC'),
            ('LV', 'SF'),
            ('GB', 'NE'),
            ('ARI', 'SEA'),
            ('TB', 'CHI'),
            ('BUF', 'MIN'),
        ],
    },
    # INGESTED from ESPN
    'W10': {
        "label": 'Week 10',
        "verified": True,
        "games": [
            ('WAS', 'NYG'),
            ('NE', 'DET'),
            ('KC', 'ATL'),
            ('HOU', 'CLE'),
            ('MIN', 'GB'),
            ('JAX', 'TEN'),
            ('MIA', 'IND'),
            ('CAR', 'NO'),
            ('BUF', 'NYJ'),
            ('SEA', 'LV'),
            ('LAR', 'ARI'),
            ('SF', 'DAL'),
            ('PIT', 'CIN'),
            ('LAC', 'BAL'),
        ],
    },
    # INGESTED from ESPN
    'W11': {
        "label": 'Week 11',
        "verified": True,
        "games": [
            ('IND', 'HOU'),
            ('MIA', 'BUF'),
            ('NO', 'CHI'),
            ('TEN', 'DAL'),
            ('TB', 'DET'),
            ('ARI', 'KC'),
            ('JAX', 'NYG'),
            ('BAL', 'CAR'),
            ('NYJ', 'LAC'),
            ('LV', 'DEN'),
            ('PIT', 'PHI'),
            ('MIN', 'SF'),
            ('CIN', 'WAS'),
        ],
    },
    # PRESERVED -- manually verified, do not auto-edit
    'TXWEEK': {
        "label": 'Thanksgiving Week (Nov 25-27)',
        "verified": True,
        "games": [
            ('GB', 'LAR'),
            ('CHI', 'DET'),
            ('PHI', 'DAL'),
            ('KC', 'BUF'),
            ('DEN', 'PIT'),
        ],
    },
    # INGESTED from ESPN
    'W12': {
        "label": 'Week 12',
        "verified": True,
        "games": [
            ('GB', 'LAR'),
            ('CHI', 'DET'),
            ('PHI', 'DAL'),
            ('KC', 'BUF'),
            ('DEN', 'PIT'),
            ('NO', 'CIN'),
            ('LV', 'CLE'),
            ('NYG', 'IND'),
            ('NYJ', 'MIA'),
            ('ATL', 'MIN'),
            ('BAL', 'HOU'),
            ('TEN', 'JAX'),
            ('WAS', 'ARI'),
            ('SEA', 'SF'),
            ('NE', 'LAC'),
            ('CAR', 'TB'),
        ],
    },
    # INGESTED from ESPN
    'W13': {
        "label": 'Week 13',
        "verified": True,
        "games": [
            ('KC', 'LAR'),
            ('DET', 'ATL'),
            ('JAX', 'CHI'),
            ('CIN', 'CLE'),
            ('WAS', 'TEN'),
            ('GB', 'NO'),
            ('SF', 'NYG'),
            ('LAC', 'TB'),
            ('MIA', 'DEN'),
            ('PHI', 'ARI'),
            ('CAR', 'MIN'),
            ('BUF', 'NE'),
            ('HOU', 'PIT'),
            ('DAL', 'SEA'),
        ],
    },
    # INGESTED from ESPN
    'W14': {
        "label": 'Week 14',
        "verified": True,
        "games": [
            ('MIN', 'NE'),
            ('ATL', 'CLE'),
            ('TEN', 'DET'),
            ('CHI', 'MIA'),
            ('DEN', 'NYJ'),
            ('IND', 'PHI'),
            ('HOU', 'WAS'),
            ('NO', 'CAR'),
            ('TB', 'BAL'),
            ('LAC', 'LV'),
            ('KC', 'CIN'),
            ('LAR', 'SF'),
            ('NYG', 'SEA'),
            ('BUF', 'GB'),
            ('PIT', 'JAX'),
        ],
    },
    # INGESTED from ESPN
    'W15': {
        "label": 'Week 15',
        "verified": True,
        "games": [
            ('SF', 'LAC'),
            ('SEA', 'PHI'),
            ('CHI', 'BUF'),
            ('MIA', 'GB'),
            ('IND', 'TEN'),
            ('CLE', 'NYG'),
            ('BAL', 'PIT'),
            ('NO', 'TB'),
            ('ATL', 'WAS'),
            ('CIN', 'CAR'),
            ('JAX', 'HOU'),
            ('NYJ', 'ARI'),
            ('DEN', 'LV'),
            ('DAL', 'LAR'),
            ('DET', 'MIN'),
            ('NE', 'KC'),
        ],
    },
    # PRESERVED -- manually verified, do not auto-edit
    'XMASWEEK': {
        "label": 'Christmas Week (Dec 24-25)',
        "verified": True,
        "games": [
            ('HOU', 'PHI'),
            ('GB', 'CHI'),
            ('BUF', 'DEN'),
            ('LAR', 'SEA'),
        ],
    },
    # INGESTED from ESPN
    'W16': {
        "label": 'Week 16',
        "verified": True,
        "games": [
            ('HOU', 'PHI'),
            ('GB', 'CHI'),
            ('BUF', 'DEN'),
            ('LAR', 'SEA'),
            ('TB', 'ATL'),
            ('CIN', 'IND'),
            ('WAS', 'MIN'),
            ('CAR', 'PIT'),
            ('LAC', 'MIA'),
            ('ARI', 'NO'),
            ('NE', 'NYJ'),
            ('CLE', 'BAL'),
            ('TEN', 'LV'),
            ('SF', 'KC'),
            ('JAX', 'DAL'),
            ('NYG', 'DET'),
        ],
    },
    # INGESTED from ESPN
    'W17': {
        "label": 'Week 17',
        "verified": True,
        "games": [
            ('BAL', 'CIN'),
            ('DEN', 'NE'),
            ('KC', 'LAC'),
            ('LAR', 'TB'),
            ('WAS', 'JAX'),
            ('NO', 'ATL'),
            ('IND', 'CLE'),
            ('NYG', 'DAL'),
            ('PIT', 'TEN'),
            ('BUF', 'MIA'),
            ('MIN', 'NYJ'),
            ('SEA', 'CAR'),
            ('LV', 'ARI'),
            ('DET', 'CHI'),
            ('PHI', 'SF'),
            ('HOU', 'GB'),
        ],
    },
    # INGESTED from ESPN
    'W18': {
        "label": 'Week 18',
        "verified": True,
        "games": [
            ('NYJ', 'BUF'),
            ('CLE', 'CIN'),
            ('LAC', 'DEN'),
            ('DET', 'GB'),
            ('JAX', 'IND'),
            ('LV', 'KC'),
            ('SEA', 'LAR'),
            ('CHI', 'MIN'),
            ('MIA', 'NE'),
            ('TB', 'NO'),
            ('PHI', 'NYG'),
            ('SF', 'ARI'),
            ('DAL', 'WAS'),
            ('ATL', 'CAR'),
            ('PIT', 'BAL'),
            ('TEN', 'HOU'),
        ],
    },
}

# Neutral-site games (international) -- zero out HFA. Manually curated.
# survivor/ingest_schedule.py surfaces candidates (anything ESPN tags with a
# non-USA venue country) but DOES NOT auto-populate this dict. Eyeball the
# candidate list from the ingester run and add entries here by hand.
NEUTRAL_SITE_GAMES = {
    ('SF', 'LAR'): 'W1: MCG, Melbourne -- NFL Australia debut',
    ('BAL', 'DAL'): 'W3: Maracana, Rio de Janeiro -- NFL Brazil series',
    ('IND', 'WAS'): 'W4: Tottenham Hotspur Stadium, London -- NFL UK series',
    ('PHI', 'JAX'): 'W5: Tottenham Hotspur Stadium, London -- NFL UK series',
    ('HOU', 'JAX'): 'W6: Wembley Stadium, London -- NFL UK series',
    ('PIT', 'NO'): 'W7: Stade de France, Paris -- NFL France debut',
    ('CIN', 'ATL'): 'W9: Santiago Bernabeu, Madrid -- NFL Spain debut',
    ('NE', 'DET'): 'W10: Allianz Arena, Munich -- NFL Germany series',
    ('MIN', 'SF'): 'W11: Estadio Banorte, Mexico City -- NFL Mexico series',
}

# The two holiday Contest Weeks = the terminal node the portfolio back-plans to.
HOLIDAY_WEEKS = ["TXWEEK", "XMASWEEK"]

# Teams appearing in BOTH holiday pools -- using one in TXWEEK removes it from XMAS.
HOLIDAY_OVERLAP = TXWEEK_POOL & XMASWEEK_POOL  # {GB,LAR,CHI,BUF,DEN,PHI}

# Chronological ordering, with holiday Contest Weeks slotted in by date.
LEG_ORDER = ['W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7', 'W8', 'W9', 'W10', 'W11', 'TXWEEK', 'W12', 'W13', 'W14', 'W15', 'XMASWEEK', 'W16', 'W17', 'W18']


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
            errs.append(f"TXWEEK pool mismatch: extra={{got-TXWEEK_POOL}}, missing={{TXWEEK_POOL-got}}")
    if "XMASWEEK" in SCHEDULE:
        got = teams_in_week("XMASWEEK")
        if got != XMASWEEK_POOL:
            errs.append(f"XMASWEEK pool mismatch: extra={{got-XMASWEEK_POOL}}, missing={{XMASWEEK_POOL-got}}")
    return errs


if __name__ == "__main__":
    errs = validate()
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
    else:
        print("Holiday pools match official rules. OK.")
    print("\nTXWEEK pool   :", sorted(teams_in_week("TXWEEK")))
    print("XMASWEEK pool :", sorted(teams_in_week("XMASWEEK")))
    print("Overlap (both):", sorted(HOLIDAY_OVERLAP))
