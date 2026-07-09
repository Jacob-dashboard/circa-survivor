"""
Circa Survivor 2026 — Data Layer
=================================
Single source of truth for team strength seeds.
Everything here is CORRECTABLE — replace placeholder values with
primary-source-verified numbers as we lock them down.

Provenance flags:
  VERIFIED    = pulled from a primary source and checked
  MARKET      = seeded from sportsbook win totals (locked snapshot, see source line)
  PLACEHOLDER = needs replacement before any real pick decision

In-season strength nudges (injuries, depth-chart shocks, line movement)
go through state.adjust_strength(); this baseline is the "as of June 2026"
anchor and should NOT be edited mid-season.
"""

# ---------------------------------------------------------------------------
# 2026 season win totals — DraftKings, current as of June 2026 (post-draft,
# post-OTAs, pre-training-camp). All 32 verified against the live DK board
# via RotoWire's aggregator; cross-checked against FOX Sports' May 18 snapshot
# (28/32 agreed; LAR moved 10.5 -> 11.5 on the Myles Garrett trade and NE
# moved 9.5 -> 10.5 post-draft, both captured here).
#
# Expect modest movement before Week 1: training-camp injuries, depth-chart
# shocks, and preseason results all push lines. Do NOT edit this dict mid-
# season. Layer those nudges via state.adjust_strength() so the June anchor
# stays auditable.
# ---------------------------------------------------------------------------
WIN_TOTALS = {
    # team_abbr: (win_total, provenance)
    "BAL": (11.5, "MARKET"),
    "LAR": (11.5, "MARKET"),
    "BUF": (10.5, "MARKET"),
    "KC":  (10.5, "MARKET"),
    "NE":  (10.5, "MARKET"),   # opened 10.5, dipped 9.5 mid-May, back to 10.5 post-draft
    "PHI": (10.5, "MARKET"),
    "DET": (10.5, "MARKET"),
    "GB":  (10.5, "MARKET"),   # moved up from placeholder 9.5
    "SF":  (10.5, "MARKET"),
    "SEA": (10.5, "MARKET"),
    "HOU": (9.5,  "MARKET"),   # moved up from placeholder 8.5
    "DEN": (9.5,  "MARKET"),
    "LAC": (9.5,  "MARKET"),
    "CIN": (9.5,  "MARKET"),
    "DAL": (9.5,  "MARKET"),   # moved up from placeholder 8.5
    "CHI": (9.5,  "MARKET"),   # moved up from placeholder 8.5
    "JAX": (8.5,  "MARKET"),
    "PIT": (8.5,  "MARKET"),
    "TB":  (8.5,  "MARKET"),   # moved down from placeholder 9.5
    "MIN": (8.5,  "MARKET"),
    "IND": (7.5,  "MARKET"),
    "NO":  (7.5,  "MARKET"),
    "NYG": (7.5,  "MARKET"),   # moved up from placeholder 6.5
    "CAR": (7.5,  "MARKET"),   # moved up from placeholder 6.5
    "WAS": (7.5,  "MARKET"),   # moved down from placeholder 8.5
    "CLE": (6.5,  "MARKET"),
    "TEN": (6.5,  "MARKET"),
    "ATL": (6.5,  "MARKET"),   # moved down from placeholder 7.5
    "LV":  (5.5,  "MARKET"),   # Las Vegas Raiders
    "NYJ": (5.5,  "MARKET"),
    "ARI": (4.5,  "MARKET"),
    "MIA": (4.5,  "MARKET"),
}

TEAMS = list(WIN_TOTALS.keys())

# Convert a season win total into a baseline Elo-style rating.
# Mapping: 8.5 wins (.500) -> 1500 (league average).
# Empirically ~ each marginal win ≈ +25 Elo around the mean.
def win_total_to_elo(win_total: float) -> float:
    return 1500 + (win_total - 8.5) * 25.0

BASE_ELO = {t: win_total_to_elo(wt) for t, (wt, _) in WIN_TOTALS.items()}

# Home-field advantage in Elo points (league-average ~ 48 Elo ≈ 1.7 pts).
HFA_ELO = 48.0
