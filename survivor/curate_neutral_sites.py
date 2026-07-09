"""
Circa Survivor 2026 — Neutral-Site Curator
==========================================
Re-runs the ingester's neutral-site detection, attaches a short context note
per venue, and writes the result into NEUTRAL_SITE_GAMES in survivor/schedule.py.

This is the second half of the ingest pipeline: the ingester FLAGS candidates
but never auto-populates them; this script's job is to commit them after
naming the venues. Replayable -- re-running fetches ESPN fresh and regenerates
the dict, so it stays current if ESPN updates a venue mid-season.

Safety:
  * ONLY the NEUTRAL_SITE_GAMES dict is touched. Everything else in
    schedule.py is preserved verbatim via a surgical regex replacement.
  * Dry-run writes to schedule.py.proposed for review. --commit flips to
    overwriting schedule.py.
  * If the dict already has entries, they are replaced (idempotent against
    a fresh ESPN fetch). Any manual curation of NEUTRAL_SITE_GAMES would be
    lost -- so curate via this script, not by hand-editing schedule.py.
"""
import json
import os
import re
import subprocess
import sys

from . import data
from . import ingest_schedule as ing
from . import schedule as sched
from . import solver
from . import state as state_mod

SCHEDULE_PATH = os.path.join(os.path.dirname(__file__), "schedule.py")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Substring-keyed venue notes. Match against the venue string the ingester
# stores -- e.g. "Melbourne Cricket Ground (Melbourne, VIC, Australia)".
VENUE_NOTES = [
    ("Melbourne",        "MCG, Melbourne -- NFL Australia debut"),
    ("Maracan",          "Maracana, Rio de Janeiro -- NFL Brazil series"),
    ("Tottenham",        "Tottenham Hotspur Stadium, London -- NFL UK series"),
    ("Wembley",          "Wembley Stadium, London -- NFL UK series"),
    ("Stade de France",  "Stade de France, Paris -- NFL France debut"),
    ("Bernab",           "Santiago Bernabeu, Madrid -- NFL Spain debut"),
    ("Bayern",           "Allianz Arena, Munich -- NFL Germany series"),
    ("Munich",           "Allianz Arena, Munich -- NFL Germany series"),
    ("Banorte",          "Estadio Banorte, Mexico City -- NFL Mexico series"),
    ("Mexico City",      "Estadio Banorte, Mexico City -- NFL Mexico series"),
]


def context_for(venue: str) -> str:
    for substr, note in VENUE_NOTES:
        if substr in venue:
            return note
    return venue  # fall through: keep the raw venue string


def collect_candidates(year: int = 2026):
    """Use the ingester's pipeline to re-fetch and return the international games."""
    ing.build_schedule_dict(year)
    return list(ing._LAST_FETCH_META["neutral_candidates"])


def format_neutral_block(candidates) -> str:
    lines = []
    for wid, away, home, venue in candidates:
        note = context_for(venue)
        desc = f"{wid}: {note}"
        lines.append(f"    ({away!r}, {home!r}): {desc!r},")
    return "\n".join(lines)


# Matches the entire `NEUTRAL_SITE_GAMES = { ... }` block, leaning on the
# fact that the dict's values are tuples-and-strings with no nested braces.
_NEUTRAL_RE = re.compile(
    r"^NEUTRAL_SITE_GAMES\s*=\s*\{[^}]*\}",
    re.MULTILINE | re.DOTALL,
)


def write_neutral_block(candidates, dry_run: bool = True) -> str:
    with open(SCHEDULE_PATH, "r") as f:
        text = f.read()
    if not _NEUTRAL_RE.search(text):
        raise RuntimeError(
            "Could not find a `NEUTRAL_SITE_GAMES = { ... }` block in schedule.py. "
            "Has the dict been reformatted to use nested braces?"
        )
    body = format_neutral_block(candidates)
    new_block = f"NEUTRAL_SITE_GAMES = {{\n{body}\n}}"
    new_text = _NEUTRAL_RE.sub(new_block, text, count=1)
    out_path = SCHEDULE_PATH + (".proposed" if dry_run else "")
    with open(out_path, "w") as f:
        f.write(new_text)
    return out_path


# ---------------------------------------------------------------------------
# Probability impact report
# ---------------------------------------------------------------------------

def print_impact(candidates, state):
    """For each candidate, show p(home)/p(away) WITH HFA vs neutral.

    Pure function over current Elo — works in dry-run AND commit modes since
    it bypasses NEUTRAL_SITE_GAMES and just toggles the `neutral` arg directly.
    Returns the count of games with zero delta (used as a wiring check;
    brief says "If any game shows no change, something didn't wire correctly").
    """
    elo = state_mod.current_elo(state)
    print()
    print("=== Win-probability impact of neutralizing each game ===")
    print(
        f"  {'Wk':<4} {'Game':<13} | "
        f"{'p(home) HFA':>11} -> {'p(home) neut':>12} ({'Δh':>6}) | "
        f"{'p(away) HFA':>11} -> {'p(away) neut':>12} ({'Δa':>6})"
    )
    print("  " + "-" * 92)
    zero_delta = []
    for wid, away, home, venue in candidates:
        p_h_hfa, p_a_hfa = solver._game_prob_live(away, home, elo, neutral=False)
        p_h_neu, p_a_neu = solver._game_prob_live(away, home, elo, neutral=True)
        dh = p_h_neu - p_h_hfa
        da = p_a_neu - p_a_hfa
        game = f"{away}@{home}"
        print(
            f"  {wid:<4s} {game:<13s} | "
            f"{p_h_hfa:>11.1%} -> {p_h_neu:>12.1%} ({dh:>+6.1%}) | "
            f"{p_a_hfa:>11.1%} -> {p_a_neu:>12.1%} ({da:>+6.1%})"
        )
        if abs(dh) < 1e-9 and abs(da) < 1e-9:
            zero_delta.append((wid, away, home))
    if zero_delta:
        print()
        print(f"  !! {len(zero_delta)} game(s) showed ZERO delta — HFA wiring is broken:")
        for z in zero_delta:
            print(f"     {z}")
    return zero_delta


# ---------------------------------------------------------------------------
# SPEC sanity test in a clean subprocess, so module reloads are automatic.
# ---------------------------------------------------------------------------

_SANITY_CODE = r"""
import json
from survivor import state as st, solver
s = st.load_state()
for i, b in {0: "chalk", 1: "chalk", 2: "contrarian", 3: "contrarian", 4: "conservation"}.items():
    st.set_bucket(s, i, b)
res, probs, meta = solver.solve(s, horizon=2)
out = {
    "status": meta["status"],
    "near_term": meta["near_term"],
    "holiday": meta["holiday"],
    "picks": {e: dict(p) for e, p in res.items()},
}
print("__SOLVER_JSON__" + json.dumps(out))
"""


def run_sanity_subprocess():
    r = subprocess.run(
        [sys.executable, "-c", _SANITY_CODE],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"Sanity subprocess failed (rc={r.returncode}):\n"
            f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
    for line in r.stdout.splitlines():
        if line.startswith("__SOLVER_JSON__"):
            return json.loads(line[len("__SOLVER_JSON__"):])
    raise RuntimeError(f"No JSON in sanity output:\n{r.stdout}")


def _diff_picks(before, after, candidates):
    intl_teams = set()
    for _w, a, h, _v in candidates:
        intl_teams.add(a); intl_teams.add(h)
    rows = []
    for e in sorted(before["picks"]):
        b = before["picks"][e]
        a = after["picks"][e]
        legs = sorted(set(b) | set(a))
        for lid in legs:
            tb, ta = b.get(lid), a.get(lid)
            if tb == ta:
                continue
            intl = (tb in intl_teams) or (ta in intl_teams)
            rows.append((e, lid, tb, ta, intl))
    return rows


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def _run(year: int = 2026, dry_run: bool = True):
    print(f"Re-fetching ESPN to refresh neutral-site candidates ({year})…")
    candidates = collect_candidates(year)
    if not candidates:
        print("No international games flagged. Nothing to do.")
        return

    print()
    print(f"=== Candidates ({len(candidates)}) ===")
    for wid, away, home, venue in candidates:
        print(f"  {wid:<5s} {away} @ {home:<4s}  {venue}")
        print(f"           note: {context_for(venue)}")

    state = state_mod.load_state()
    print_impact(candidates, state)

    existing = sched.NEUTRAL_SITE_GAMES
    if existing:
        print()
        print(f"Note: NEUTRAL_SITE_GAMES already has {len(existing)} entries; "
              "they will be replaced by the fresh ESPN list.")

    if dry_run:
        # In dry-run, just preview by showing solver state with the schedule
        # currently on disk (whatever it has).
        print()
        print("=== Solver state with schedule.py as it sits on disk (preview) ===")
        cur = run_sanity_subprocess()
        print(f"  status   : {cur['status']}")
        print(f"  near-term: {cur['near_term']}")
        print(f"  holiday  : {cur['holiday']}")

        out_path = write_neutral_block(candidates, dry_run=True)
        print()
        print(f"Wrote: {out_path}  (dry_run=True)")
        print("Review with `diff survivor/schedule.py survivor/schedule.py.proposed`,")
        print("then re-run with --commit to overwrite schedule.py.")
        return

    # ----- Commit path -----
    # To produce a meaningful BEFORE/AFTER diff (rather than one keyed off
    # whatever state happens to be on disk), the commit briefly writes an
    # empty NEUTRAL_SITE_GAMES block, captures the solver decision under
    # "no curation", then overwrites with the populated block and captures
    # the curated solver decision. Net file state is the populated block.
    print()
    print("=== Solver state (BEFORE) — temporarily empty NEUTRAL_SITE_GAMES, ")
    print("    to baseline what the solver would do WITHOUT this curation ===")
    write_neutral_block([], dry_run=False)
    before = run_sanity_subprocess()
    print(f"  status   : {before['status']}")
    print(f"  near-term: {before['near_term']}")
    print(f"  holiday  : {before['holiday']}")

    out_path = write_neutral_block(candidates, dry_run=False)
    print()
    print(f"Wrote: {out_path}  (dry_run=False)")

    print()
    print("=== Solver state (AFTER) — populated NEUTRAL_SITE_GAMES, HFA zeroed ===")
    after = run_sanity_subprocess()
    print(f"  status   : {after['status']}")
    print(f"  near-term: {after['near_term']}")
    print(f"  holiday  : {after['holiday']}")

    print()
    print("=== Pick diff (HFA zeroed for the 9 international games) ===")
    changes = _diff_picks(before, after, candidates)
    if not changes:
        print("  (no pick changes — none of the borderline calls touched these games)")
    else:
        for e, lid, tb, ta, intl in changes:
            tag = "  [intl-game team]" if intl else ""
            print(f"  Entry {e}  {lid:<8s}  {tb} -> {ta}{tag}")


if __name__ == "__main__":
    dry = "--commit" not in sys.argv
    _run(year=2026, dry_run=dry)
