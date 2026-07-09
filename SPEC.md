# Circa Survivor 2026 — Portfolio Model SPEC

## 1. Purpose and objective

A decision-support model for one user's **2 entries** in the Circa Survivor 2026
NFL contest ($1,000 entry, ~$20M pool). The model is re-solved weekly as injuries,
lines, and survival state evolve. Live state persists in `survivor/season_state.json`.

> **Entry count history:** planned at 5 entries; the user purchased **2**.
> `state.N_ENTRIES` is the single source of truth. All modules size off the
> entries dict in state, so the solver/UI/CLI adapt automatically.

The user is not chasing the single highest-EV entry. Multiple entries are run to
**engineer hedging optionality**. The real objective:

> **Maximize the probability of arriving at the two holiday Contest Weeks with
> multiple entries alive holding *distinct, hedge-able teams*** — so value can
> be locked through (a) contradictory picks across the user's own entries and
> (b) external sportsbook hedges.

Success metric: expected number of entries alive entering Thanksgiving Week,
with cross-entry decorrelation as the tiebreaker. **Survival dominates the
objective; decorrelation shapes choices among comparable-survival options.**

## 2. Verified contest rules (Rev. 5/16/2026)

| # | Rule | Implication |
|---|---|---|
| 6a | Pick to win, no spread. **Tie = LOSS.** | Coinflips are not coinflips. |
| 7 | Up to 20 Contest Weeks: 18 standard + 2 holiday. | Up to 20 picks total. |
| 8 | **Thanksgiving Week** (Nov 25/26/27) = ONE pick from pool `{GB, LAR, CHI, DET, PHI, DAL, KC, BUF, DEN, PIT}`. Roster exhaustion = elimination. | Hard reservation constraint. |
| 9 | **Christmas Week** (Dec 24/25) = ONE pick from pool `{HOU, PHI, GB, CHI, BUF, DEN, LAR, SEA}`. Roster exhaustion = elimination. | Hard reservation constraint. |
| 10 | Multiple entries MAY make contradictory picks. | Enables intra-portfolio straddle. |
| 19d-iii | Mass-extinction split: if all remaining entries lose in the same Contest Week, prize splits among entries who submitted that week. | Survival on a chalk week is non-negative even when others fold. |

Each team is usable **once per entry, whole season**.

## 3. Design commitments

1. **Entries are discrete strategy buckets**, not a single chalk→contrarian dial.
   Buckets: `chalk`, `contrarian`, `conservation`. Aggression differentiated by bucket.
2. **The two holiday Contest Weeks are the terminal node** the portfolio back-plans toward.
3. **Rolling horizon with reservations**:
   - NEAR-TERM (current week + `horizon` weeks, default 2): picks COMMITTED. Decorrelation active.
   - HOLIDAY weeks: always solved as RESERVATIONS, re-solved every week.
   - IN-BETWEEN weeks (beyond horizon, before holidays): NOT pick-committed. Only matter
     insofar as they must not exhaust the holiday pools.
4. **Primary-source verification before any number is trusted.** Win totals: 6 of 32 verified;
   the rest are `PLACEHOLDER`. Schedule: W1 stub + the two holiday weeks; W2–W18 not yet ingested.
5. **Differentiated aggression across buckets.** Uniform aggression over-bleeds and kills
   the multi-entry precondition the hedging thesis depends on.
6. **Future-value conservation (use bad teams early).** Strong teams are scarce
   season-long resources. `solver.future_value(team)` prices each team's option
   value — `(win_total − 8.5)/3`, floored at 0, plus `+0.3` per holiday-pool
   membership — and the objective subtracts `future_value_weight × FV` from
   every NON-holiday pick term (default weight `0.5`). Effect: a sub-.500 team
   in a rare favorable spot (LV −175 over MIA) is FREE to burn, while burning
   PHI (10.5 wins, in both holiday pools, FV ≈ 1.27) in an ordinary week is
   heavily taxed. Holiday weeks are exempt — that's where conserved teams get
   spent. Caution: weights ≫ 0.5 can overwhelm the concentration penalty and
   stack both entries on the same burn-friendly favorite; the UI's stack
   warning catches this.

## 4. Module status

| Module | Status | Role |
|---|---|---|
| `survivor/data.py` | partial: 6/32 win totals verified | Team strength seeds, HFA, Elo mapping. |
| `survivor/schedule.py` | partial: W1 stub + 2 holiday weeks | Contest-week structure, official pool validation. |
| `survivor/probability.py` | done | Elo + moneyline-devig blend → per-team win probs. |
| `survivor/state.py` | done | Live mutable layer, JSON-persisted. |
| `survivor/solver.py` | done | PuLP MILP portfolio optimizer. |

## 5. Known defects (priority order)

1. **Ingest full Weeks 2–18 schedule.** Without it the rolling horizon collapses to W1 only
   and the holiday roster-exhaustion constraint can't see overlap conflicts that hide in W2–W17.
2. **Lock verified win totals to replace the 26 placeholders.** Every prob in those games is
   currently a guess; market lines move it but Elo-only weeks are still seeded from placeholders.
3. Wire a moneyline ingester. `state.set_line()` exists; nothing populates it yet.
4. Add Week-1-style stub legs as ingestion progresses so the horizon expands beyond W1.

## 5a. Rolling-horizon-with-reservations architecture

The solver runs one MILP, but legs play two different roles:

```
 current   ┌── near-term horizon ──┐   in-between weeks   ┌── holiday weeks ──┐
   ↓       │  pick-COMMITTED       │   (not picked here)  │  RESERVED         │
  Wk N ───►│  W(N), W(N+1)         │  W(N+2)…W17          │  TXWEEK, XMASWEEK │
           └──────────────────────────────────────────────────────────────────┘
                  decorrelation active   ┘                ┘ decorrelation active
                                         └ roster constraint propagates: every
                                           alive entry must reserve >=1 unused
                                           pool team for each holiday week.
```

Re-solve weekly. Near-term picks lock as actual games complete; reservations
slide and get re-optimized as data sharpens.

## 5b. Key strategic finding — the Christmas decorrelation/safety tradeoff

The XMASWEEK pool is **coinflip-heavy**: at the current placeholder seeds, only
PHI is above 55%; CHI, SEA, DEN cluster at ~53%; GB, BUF, LAR sit slightly below
50%. The implication is unavoidable:

> **You cannot simultaneously demand high per-pick safety AND meaningful
> decorrelation at Christmas. The pool will not support both.**

Spreading entries across distinct teams in this pool requires accepting
~53% picks for at least one entry. This is a **risk-preference dial**, exposed
as `holiday_min_prob`. Default `0.50` admits the coinflip cluster (spread, but
some entries fail). Raising to `0.55` forces stacking on PHI (survival, but
correlated). Neither is wrong; they are different bets. **There is no setting
that produces both.**

With **2 entries** the tension is softer than the original 5-entry plan: PHI +
one ~53% coinflip covers both entries with only one below-chalk pick, and an
endgame straddle (both entries on opposite sides of one game, Rule 10) is the
classic 2-entry play — it guarantees exactly one survivor into the next leg.

## 5c. Two-entry bucket strategy

With 2 entries the recommended buckets are **chalk + contrarian**:
- Entry 0 `chalk` — max survival, market-consensus picks.
- Entry 1 `contrarian` — decorrelated route that trades a few points of
  per-week safety for independence; if a chalk-killing upset lands, this
  entry is positioned to survive it.

`conservation` (hoarding strong teams for later) matters less with 2 entries —
its main value was protecting the 5-entry portfolio's long tail. Decorrelation
between the two entries is still active and still the tiebreaker.

## Irreducible-variance disclaimer

This model sharpens edge and engineers hedging optionality. It does not
manufacture certainty. The contest has irreducible variance — a single
upset can kill multiple entries simultaneously, and that risk is the price
of admission, not a defect the model corrects.
