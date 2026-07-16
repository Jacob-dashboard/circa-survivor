"""
Circa Survivor 2026 — CLI
=========================
The interaction surface for the model. Most weeks, you live in two commands:

    python -m survivor             # default: status (entry table + holiday pools)
    python -m survivor forecast    # re-solve and show this week's recommendation

The full list:

    status       (default) Entry alive/used/pick table + holiday roster remaining.
    forecast     Re-solve and show committed + reserved picks per entry.
    pools        Per-leg team pools, marked AVAILABLE / USED for each entry.
    pick         Lock a pick:  pick <entry> <leg> <team> [--lost]
    bucket       Assign a strategy bucket:  bucket <entry> <chalk|contrarian|conservation>
    line         Add a moneyline override:  line <leg> <away> <home> <ml_away> <ml_home>
    nudge        Manual strength adjustment:  nudge <team> <delta_elo> [--note "..."]
    advance      Move current_leg forward:  advance <leg>
    check        Integrity sweep: schedule pools, solver runs, no roster exhaustion,
                 no PLACEHOLDER provenance, no stale state.

Discipline:
  - Every command that mutates state writes to season_state.json IMMEDIATELY
    on success. The JSON is the source of truth between sessions.
  - `forecast` is display-only — it never writes state.
  - The CLI is deliberately argparse-only; no Click/Typer/Rich. Plain text
    output is easy to grep, pipe, and screenshot.
"""
import argparse
import sys

from . import data
from . import schedule as sched
from . import solver
from . import state as state_mod


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _hr(width=78, char="-"):
    print(char * width)


def _alive_mark(alive):
    return "alive" if alive else "OUT  "


def _legs_done(state, entry_idx):
    return list(state["entries"][entry_idx]["picks"].keys())


def _ordered_legs():
    """LEG_ORDER, but only legs that actually exist in SCHEDULE."""
    return [lid for lid in sched.LEG_ORDER if lid in sched.SCHEDULE]


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status(state, args):
    print(f"Circa Survivor 2026 — current_leg: {state['current_leg']}")
    _hr()
    print(f"{'Entry':<6}{'Bucket':<14}{'Alive':<7}{'Used':<6}Picks")
    _hr()
    for e in sorted(state["entries"]):
        entry = state["entries"][e]
        picks_str = ", ".join(f"{lid}={t}" for lid, t in entry["picks"].items()) or "(none yet)"
        print(
            f"{str(int(e)+1):<6}"
            f"{(entry.get('bucket') or '—'):<14}"
            f"{_alive_mark(entry['alive']):<7}"
            f"{len(entry['used_teams']):<6}"
            f"{picks_str}"
        )

    # Holiday roster remaining per entry — the constraint that kills you if ignored
    print()
    _hr()
    print("Holiday roster remaining (Rules 8 & 9):")
    _hr()
    for hw, pool, label in [
        ("TXWEEK", sched.TXWEEK_POOL, "TXWEEK   (10)"),
        ("XMASWEEK", sched.XMASWEEK_POOL, "XMASWEEK (8) "),
    ]:
        print(f"\n{label}  full pool: {','.join(sorted(pool))}")
        for e in sorted(state["entries"]):
            entry = state["entries"][e]
            used = set(entry["used_teams"])
            remaining = sorted(pool - used)
            already_locked = entry["picks"].get(hw)
            if already_locked:
                tag = f"LOCKED: {already_locked}"
            elif not remaining:
                tag = "EXHAUSTED — entry will die without picking"
            else:
                tag = ",".join(remaining)
            print(f"  Entry {int(e)+1}: {tag}")

    # Quick sanity flags
    print()
    print(f"({sum(1 for e in state['entries'].values() if e['alive'])} of "
          f"{len(state['entries'])} entries alive)")


# ---------------------------------------------------------------------------
# pools
# ---------------------------------------------------------------------------

def cmd_pools(state, args):
    legs = _ordered_legs()
    filt = set(args.legs) if args.legs else None
    for lid in legs:
        if filt and lid not in filt:
            continue
        leg = sched.SCHEDULE[lid]
        pool = sorted(sched.teams_in_week(lid))
        is_holiday = lid in sched.HOLIDAY_WEEKS
        tag = " [HOLIDAY]" if is_holiday else ""
        print(f"\n{lid} — {leg['label']}{tag}  ({len(pool)} teams)")
        print(f"  pool: {','.join(pool)}")
        for e in sorted(state["entries"]):
            entry = state["entries"][e]
            used = set(entry["used_teams"])
            avail = [t for t in pool if t not in used]
            locked = entry["picks"].get(lid)
            if locked:
                print(f"  Entry {int(e)+1}: locked {locked}")
            else:
                print(f"  Entry {int(e)+1}: {len(avail)}/{len(pool)} available "
                      f"({'all' if len(avail) == len(pool) else ','.join(avail)})")


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------

def cmd_forecast(state, args):
    res, probs, meta = solver.solve(
        state,
        horizon=args.horizon,
        min_prob=args.min_prob,
        holiday_min_prob=args.holiday_min_prob,
        endgame=args.endgame,
    )
    print(f"Forecast — current_leg: {state['current_leg']}  horizon: {args.horizon}")
    print(f"Status: {meta['status']}")
    print(f"Near-term (committed once locked): {meta['near_term']}")
    print(f"Holiday (always reserved):         {meta['holiday']}")
    if meta["straddles"]:
        print(f"Straddles in play (endgame): {meta['straddles']}")
    print()

    leg_order = [lid for lid in sched.LEG_ORDER if lid in (set(meta["near_term"]) | set(meta["holiday"]))]
    for e in sorted(res):
        bucket = state["entries"][e].get("bucket") or "—"
        print(f"Entry {int(e)+1}  ({bucket}):")
        for lid in leg_order:
            team = res[e].get(lid)
            if team is None:
                continue
            already_locked = lid in state["entries"][e]["picks"]
            tag = "[locked]" if already_locked else (
                "[holiday/reserve]" if lid in meta["holiday"] else "[recommend]"
            )
            p = probs.get(lid, {}).get(team)
            p_str = f"{p:5.1%}" if p is not None else "  n/a"
            print(f"  {lid:<10s} {team:<5s} {p_str}  {tag}")
        print()

    # Decorrelation summary — answers "are my chalks doubled up?"
    print("Decorrelation summary:")
    for lid in meta["near_term"] + meta["holiday"]:
        teams = [res[e].get(lid) for e in sorted(res) if res[e].get(lid)]
        n = len(set(teams))
        flag = "  ⚠ stacked" if n < len(teams) else ""
        print(f"  {lid:<10s} distinct picks: {n} of {len(teams)}{flag}")


# ---------------------------------------------------------------------------
# pick (lock) / bucket / line / nudge / advance — mutators
# ---------------------------------------------------------------------------

def cmd_pick(state, args):
    e, lid, team = args.entry, args.leg, args.team
    if e not in state["entries"]:
        valid = ", ".join(sorted(state["entries"]))
        raise SystemExit(f"Unknown entry {e!r}. Valid entries: {valid}")
    if lid not in sched.SCHEDULE:
        raise SystemExit(f"Unknown leg {lid!r}. Try one of: {_ordered_legs()}")
    pool = sched.teams_in_week(lid)
    if team not in pool:
        raise SystemExit(f"{team} is not in the {lid} pool. Pool: {sorted(pool)}")
    used = set(state["entries"][e]["used_teams"])
    if team in used and team != state["entries"][e]["picks"].get(lid):
        raise SystemExit(f"Entry {int(e)+1} already used {team} in another leg. Pick blocked.")
    survived = not args.lost
    state_mod.record_pick(state, e, lid, team, survived=survived)
    state_mod.save_state(state)
    msg = "LOST (entry eliminated)" if args.lost else "survived"
    print(f"Recorded: Entry {int(e)+1}  {lid}  {team}  -> {msg}")


def cmd_bucket(state, args):
    if args.entry not in state["entries"]:
        valid = ", ".join(sorted(state["entries"]))
        raise SystemExit(f"Unknown entry {args.entry!r}. Valid entries: {valid}")
    if args.bucket not in {"chalk", "contrarian", "conservation", "neutral"}:
        raise SystemExit("Bucket must be one of: chalk, contrarian, conservation")
    state_mod.set_bucket(state, args.entry, args.bucket)
    state_mod.save_state(state)
    print(f"Entry {int(args.entry)+1} bucket -> {args.bucket}")


def cmd_line(state, args):
    if args.leg not in sched.SCHEDULE:
        raise SystemExit(f"Unknown leg {args.leg!r}. Try: {_ordered_legs()}")
    pool = sched.teams_in_week(args.leg)
    if args.away not in pool or args.home not in pool:
        raise SystemExit(f"{args.away}/{args.home} not in {args.leg} pool ({sorted(pool)}).")
    state_mod.set_line(
        state, args.leg, args.away, args.home,
        ml_away=args.ml_away, ml_home=args.ml_home,
        market_weight=args.market_weight,
    )
    state_mod.save_state(state)
    print(f"Line set: {args.leg}  {args.away} ({args.ml_away:+d}) @ "
          f"{args.home} ({args.ml_home:+d})  market_weight={args.market_weight}")


def cmd_nudge(state, args):
    if args.team not in data.BASE_ELO:
        raise SystemExit(f"Unknown team {args.team!r}.")
    state_mod.adjust_strength(state, args.team, args.delta, note=args.note)
    state_mod.save_state(state)
    print(f"Nudged {args.team} by {args.delta:+.0f} Elo. "
          f"Cumulative adjustment: {state['elo_adjustments'].get(args.team, 0):+.0f}")
    if args.note:
        print(f"  note: {args.note}")


def cmd_advance(state, args):
    if args.leg not in sched.SCHEDULE:
        raise SystemExit(f"Unknown leg {args.leg!r}. Try: {_ordered_legs()}")
    old = state["current_leg"]
    state["current_leg"] = args.leg
    state_mod.save_state(state)
    print(f"current_leg: {old} -> {args.leg}")


# ---------------------------------------------------------------------------
# lines / verify / injuries — ESPN ingesters
# ---------------------------------------------------------------------------

def cmd_lines(state, args):
    from . import ingest_lines
    leg = args.leg or state["current_leg"]
    if leg not in ingest_lines.LEG_TO_ESPN_WEEK:
        raise SystemExit(
            f"Cannot map {leg!r} to an ESPN week. "
            f"Valid: {sorted(ingest_lines.LEG_TO_ESPN_WEEK)}"
        )
    applied, skipped = ingest_lines.ingest_lines_for_leg(state, leg, year=args.year)
    print(f"Moneylines for {leg} (DraftKings via ESPN, year={args.year}):")
    if applied:
        for away, home, ml_a, ml_h, tag in applied:
            print(f"  {away:>3s} ({ml_a:+4d})  @  {home:<3s} ({ml_h:+4d})  [{tag}]")
        print(f"\nWrote {len(applied)} line(s) into state.leg_overrides[{leg!r}]['lines'].")
        print(f"Blend weight on next forecast: 0.85 market + 0.15 Elo (default).")
    else:
        print("  (no DraftKings lines posted yet for any game in this Contest Week)")
    if skipped:
        print(f"\nSkipped {len(skipped)} game(s) with no posted line:")
        for away, home, reason in skipped:
            print(f"  {away} @ {home}  -- {reason}")


def cmd_verify(state, args):
    from . import ingest_results
    leg = args.leg or state["current_leg"]
    if leg not in ingest_results.LEG_TO_ESPN_WEEK:
        raise SystemExit(
            f"Cannot map {leg!r} to an ESPN week. "
            f"Valid: {sorted(ingest_results.LEG_TO_ESPN_WEEK)}"
        )
    results, _ = ingest_results.verify_leg(state, leg, year=args.year)
    print(f"Result verification for {leg}:")
    if not results:
        print("  (no entry has a pick locked for this Contest Week — nothing to verify)")
        return
    for e, team, status, info in results:
        score = ""
        if info and info.get("home_score") is not None:
            score = f"  final {info['away']}-{info['home']}: {info['away_score']}-{info['home_score']}"
        print(f"  Entry {int(e)+1}  picked {team:<4s} -> {status}{score}")
    # quick alive summary
    alive = sum(1 for e in state["entries"].values() if e["alive"])
    print(f"\nAlive after verification: {alive} of {len(state['entries'])}")


def cmd_injuries(state, args):
    from . import ingest_injuries
    payload = ingest_injuries.fetch_injuries()
    severity = "all" if args.all else "high"
    by_team = ingest_injuries.parse_injuries(payload, severity=severity)

    if args.team:
        key = args.team.upper()
        rows = by_team.get(key)
        if not rows:
            print(f"No {severity}-severity injuries reported for {key}.")
            return
        teams = [key]
    else:
        # League-wide: order teams by newsworthiness so QB-Out teams float up.
        teams = sorted(
            by_team.keys(),
            key=lambda t: -ingest_injuries.team_alert_score(by_team[t]),
        )

    print(f"ESPN injury report — severity={severity}  ({len(teams)} team(s))")
    for abbr in teams:
        rows = ingest_injuries.sort_by_priority(by_team[abbr])
        score = ingest_injuries.team_alert_score(rows)
        print(f"\n{abbr}  ({len(rows)} listed, alert score {score})")
        for r in rows:
            detail = f"  -- {r['detail']}" if r["detail"] else ""
            print(f"  [{r['status']:<24s}] {r['position']:<4s} {r['name']:<26s} {r['type']}{detail}")


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def cmd_check(state, args):
    failures = []

    # 1. Schedule integrity
    errs = sched.validate()
    if errs:
        failures.extend(f"schedule: {e}" for e in errs)
    else:
        print("[ok] schedule.validate(): TXWEEK and XMASWEEK pools match official rules")

    # 2. No PLACEHOLDER provenance left
    ph = [t for t, (_, prov) in data.WIN_TOTALS.items() if prov == "PLACEHOLDER"]
    if ph:
        failures.append(f"data: {len(ph)} placeholder win totals remain: {ph}")
    else:
        print(f"[ok] data.WIN_TOTALS: all 32 teams verified (no PLACEHOLDER provenance)")

    # 3. Solver runs
    try:
        res, probs, meta = solver.solve(state, horizon=2)
        if meta["status"] != "Optimal":
            failures.append(f"solver: status {meta['status']!r}, expected Optimal")
        else:
            print(f"[ok] solver.solve(): Optimal  "
                  f"near={meta['near_term']}  holiday={meta['holiday']}")
    except Exception as ex:
        failures.append(f"solver: raised {type(ex).__name__}: {ex}")
        res = probs = meta = None

    # 4. No alive entry has burned a full holiday pool
    for e in sorted(state["entries"]):
        entry = state["entries"][e]
        if not entry["alive"]:
            continue
        used = set(entry["used_teams"])
        for hw, pool in [("TXWEEK", sched.TXWEEK_POOL), ("XMASWEEK", sched.XMASWEEK_POOL)]:
            if hw in entry["picks"]:
                continue  # already picked, irrelevant
            if not (pool - used):
                failures.append(
                    f"roster: entry {e} has exhausted the {hw} pool "
                    f"(used {sorted(used & pool)}) — will die without picking"
                )
    if not any(f.startswith("roster:") for f in failures):
        print("[ok] holiday rosters: every alive entry has >=1 unused team in TXWEEK and XMASWEEK")

    # 5. Decorrelation sanity on a forecast (advisory, not a failure)
    if res is not None:
        for lid in meta["near_term"] + meta["holiday"]:
            teams = [res[e].get(lid) for e in res if res[e].get(lid)]
            n_distinct = len(set(teams))
            if n_distinct == 1 and len(teams) >= 3:
                print(f"[warn] forecast {lid}: all {len(teams)} alive entries stacked on {teams[0]}")

    # 6. State internal consistency
    for e in sorted(state["entries"]):
        entry = state["entries"][e]
        used = entry["used_teams"]
        if len(used) != len(set(used)):
            failures.append(f"state: entry {e} used_teams contains duplicates: {used}")
        for lid, t in entry["picks"].items():
            if t not in used:
                failures.append(f"state: entry {e} picked {t} in {lid} but it's not in used_teams")

    print()
    if failures:
        print(f"=== CHECK FAILED ({len(failures)} issue{'s' if len(failures)!=1 else ''}) ===")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("=== CHECK PASSED ===")


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def _build_parser():
    p = argparse.ArgumentParser(
        prog="survivor",
        description="Circa Survivor 2026 portfolio CLI.",
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("status", help="show entry table + holiday roster (default)")

    p_pools = sub.add_parser("pools", help="show team pools per Contest Week")
    p_pools.add_argument("legs", nargs="*", help="optional leg IDs to filter (e.g. W1 TXWEEK)")

    p_fc = sub.add_parser("forecast", help="re-solve and display recommended picks")
    p_fc.add_argument("--horizon", type=int, default=2)
    p_fc.add_argument("--min-prob", type=float, default=0.55, dest="min_prob")
    p_fc.add_argument("--holiday-min-prob", type=float, default=0.50, dest="holiday_min_prob")
    p_fc.add_argument("--endgame", action="store_true",
                      help="enable straddle reward (endgame mode)")

    p_pick = sub.add_parser("pick", help="lock a pick into season_state.json")
    p_pick.add_argument("entry")
    p_pick.add_argument("leg")
    p_pick.add_argument("team")
    p_pick.add_argument("--lost", action="store_true", help="record the pick as a loss")

    p_bk = sub.add_parser("bucket", help="set an entry's strategy bucket")
    p_bk.add_argument("entry")
    p_bk.add_argument("bucket", choices=["chalk", "contrarian", "conservation", "neutral"])

    p_ln = sub.add_parser("line", help="add a moneyline override for a game")
    p_ln.add_argument("leg")
    p_ln.add_argument("away")
    p_ln.add_argument("home")
    p_ln.add_argument("ml_away", type=int)
    p_ln.add_argument("ml_home", type=int)
    p_ln.add_argument("--market-weight", type=float, default=0.85, dest="market_weight")

    p_nd = sub.add_parser("nudge", help="hand-tune a team's Elo (e.g. injury news)")
    p_nd.add_argument("team")
    p_nd.add_argument("delta", type=float)
    p_nd.add_argument("--note", default=None)

    p_av = sub.add_parser("advance", help="set current_leg to a new Contest Week ID")
    p_av.add_argument("leg")

    p_ln_ing = sub.add_parser("lines", help="ingest DraftKings moneylines from ESPN")
    p_ln_ing.add_argument("leg", nargs="?", default=None,
                          help="leg ID (defaults to current_leg)")
    p_ln_ing.add_argument("--year", type=int, default=2026)

    p_ver = sub.add_parser("verify", help="record survived/lost from ESPN final scores")
    p_ver.add_argument("leg", nargs="?", default=None,
                       help="leg ID (defaults to current_leg)")
    p_ver.add_argument("--year", type=int, default=2026)

    p_inj = sub.add_parser("injuries", help="surface significant injuries from ESPN")
    p_inj.add_argument("team", nargs="?", default=None,
                       help="filter to one team abbreviation")
    p_inj.add_argument("--all", action="store_true",
                       help="include Questionable status (default: Out/Doubtful/IR/PUP/Suspended only)")

    sub.add_parser("check", help="integrity sweep across data + schedule + solver + state")

    return p


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    cmd = args.cmd or "status"  # default to status
    state = state_mod.load_state()
    dispatch = {
        "status":   cmd_status,
        "pools":    cmd_pools,
        "forecast": cmd_forecast,
        "pick":     cmd_pick,
        "bucket":   cmd_bucket,
        "line":     cmd_line,
        "nudge":    cmd_nudge,
        "advance":  cmd_advance,
        "lines":    cmd_lines,
        "verify":   cmd_verify,
        "injuries": cmd_injuries,
        "check":    cmd_check,
    }
    dispatch[cmd](state, args)


if __name__ == "__main__":
    main()
