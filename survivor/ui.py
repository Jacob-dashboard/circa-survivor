"""
Circa Survivor 2026 — Streamlit UI (v2, entry-first)
=====================================================
Run with:
    .venv/bin/streamlit run survivor/ui.py

Layout philosophy (v2): the user thinks in ENTRIES, not tools.
  * 🎯 This Week      — one card per entry: pick, matchup, spread, lock. Done.
  * Entry tabs        — one tab per entry: this week's action + a bracket-style
                        season roadmap (locked ✓ → current → planned → 🎄 → 🎁),
                        alternatives table, used-teams and holiday-pool status.
  * 📈 Market         — line movement (open→current) + VSiN betting splits.
  * 🔧 Data & Tools   — pools, injuries, lines ingest, result verify, integrity
                        check. Everything operational lives in expanders here.

Solver dials (horizon / floors / endgame) live in the sidebar under Advanced —
set once, apply everywhere. All state writes go through state.save_state(), so
the CLI and UI stay interchangeable.
"""
import copy
import math
import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

from survivor import data, schedule as sched, solver
from survivor import state as state_mod
from survivor import ingest_lines, ingest_results, ingest_injuries, ingest_splits


# ---------------------------------------------------------------------------
# Page config + state
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Circa Survivor 2026",
    page_icon="🏈",
    layout="wide",
)

# --- Visual polish -----------------------------------------------------------
# Curated, low-risk styling: real typography (Inter), softer cards, cleaner
# chrome. Colors come from .streamlit/config.toml (navy + Vegas gold).
# Deliberately targeted selectors only — no layout overrides.
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

      html, body, [data-testid="stAppViewContainer"] * {
          font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
      }
      h1, h2, h3 { font-weight: 800; letter-spacing: -0.02em; }
      h2 {
          border-bottom: 1px solid rgba(232, 179, 57, .30);
          padding-bottom: .35rem;
      }

      /* Entry cards and bordered containers: softer, elevated */
      div[data-testid="stVerticalBlockBorderWrapper"] {
          border-radius: 14px;
          border-color: rgba(232, 179, 57, .18) !important;
          background: linear-gradient(180deg, rgba(232,179,57,.03), rgba(20,26,41,.0));
      }

      /* Buttons: rounded, confident */
      .stButton > button {
          border-radius: 10px;
          font-weight: 600;
      }

      /* Metrics: heavier numbers */
      div[data-testid="stMetricValue"] { font-weight: 700; }

      /* Tab labels: a touch more presence */
      button[role="tab"] p { font-weight: 600; }

      /* Hide Streamlit footer for a cleaner app feel */
      footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Load state defensively — a malformed/empty season_state.json on a fresh host
# should not produce a blank page. Fall back to a clean default and say so.
try:
    state = state_mod.load_state()
    if "entries" not in state or not state["entries"]:
        raise ValueError("no entries in state")
except Exception as ex:
    st.warning(f"Could not load season_state.json ({ex}); using a fresh default state.")
    import copy as _copy
    state = _copy.deepcopy(state_mod.DEFAULT_STATE)

loaded_legs = [lid for lid in sched.LEG_ORDER if lid in sched.SCHEDULE]
entry_ids = sorted(state["entries"].keys())


# ---------------------------------------------------------------------------
# Shared, cached data fetch
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def _game_meta(year, leg_id):
    # Never let an ESPN hiccup (slow/blocked from the host) blank the page:
    # this runs at load time, before the header/tabs render.
    try:
        return ingest_lines.fetch_game_meta(year, leg_id)
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def _season_records(year):
    """Live W/L records from ESPN standings. Empty dict until games start."""
    try:
        return ingest_results.fetch_records(year)
    except Exception:
        return {}


RECORDS = _season_records(2026)


def _rec(team):
    """' (3-1)' once the season starts; '' in the offseason so UI stays clean."""
    r = RECORDS.get(team)
    return f" ({r['summary']})" if r else ""


# ---------------------------------------------------------------------------
# Sidebar — settings only
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🏈 Circa Survivor")
    st.caption(f"{len(entry_ids)} entries · 2026 season")

    cur_idx = loaded_legs.index(state["current_leg"]) if state["current_leg"] in loaded_legs else 0
    new_current = st.selectbox("Current Contest Week", loaded_legs, index=cur_idx)
    if new_current != state["current_leg"]:
        state["current_leg"] = new_current
        state_mod.save_state(state)
        st.rerun()

    st.divider()
    st.subheader("Default buckets")
    st.caption("Season default per entry. Override individual weeks on each "
               "entry's tab (🎛 Per-week strategy).")
    for e in entry_ids:
        entry = state["entries"][e]
        current = entry.get("bucket")
        options = ["—", "chalk", "contrarian", "conservation"]
        idx = options.index(current) if current in options else 0
        n_over = len(entry.get("leg_buckets", {}))
        label = f"Entry {e}" + (f" ({n_over} week override{'s' if n_over != 1 else ''})" if n_over else "")
        new_bucket = st.selectbox(label, options, index=idx, key=f"bucket_{e}")
        new_val = None if new_bucket == "—" else new_bucket
        if new_val != current:
            state_mod.set_bucket(state, e, new_val)
            state_mod.save_state(state)
            st.rerun()

    with st.expander("⚙ Advanced (solver dials)"):
        horizon = st.slider(
            "Horizon (weeks planned)", 1, 17, 17,
            help="How many upcoming weeks get provisional picks. Default 17 = "
                 "plan the whole season (re-solved weekly; distant picks are "
                 "provisional). Lower it only if you want to focus the model "
                 "on the near term. Weeks you give a per-week strategy are "
                 "always planned regardless of this slider.",
        )
        min_prob = st.slider("min_prob (weekly floor)", 0.40, 0.70, 0.55, 0.01)
        holiday_min_prob = st.slider("holiday_min_prob", 0.40, 0.65, 0.50, 0.01)
        future_value_weight = st.slider(
            "Team conservation", 0.0, 1.2, 0.5, 0.05,
            help="How hard to avoid burning strong / holiday-pool teams in "
                 "ordinary weeks. 0 = pure win-prob greed; higher = save the "
                 "good teams, ride bad-team favorites early.",
        )
        endgame = st.checkbox("Endgame mode (straddles)", value=False)


# ---------------------------------------------------------------------------
# Solve once per rerun — every view reads from this
# ---------------------------------------------------------------------------

current_leg = state["current_leg"]

# A per-week strategy override is a declaration of intent to plan that week.
# If any override falls outside the slider's window, extend the horizon so
# the week actually gets solved — otherwise the roadmap shows the strategy
# tag with no suggested pick, which reads as "blank".
_scope_legs, _, _ = solver._weeks_to_solve(state, horizon)
_overridden = {
    lid for ent in state["entries"].values()
    for lid in ent.get("leg_buckets", {})
}
effective_horizon = 17 if (_overridden - set(_scope_legs)) else horizon

solver_error = None
try:
    res, probs, meta = solver.solve(
        state, horizon=effective_horizon, min_prob=min_prob,
        holiday_min_prob=holiday_min_prob,
        future_value_weight=future_value_weight, endgame=endgame,
    )
except Exception as ex:
    solver_error = f"{type(ex).__name__}: {ex}"
    res, probs, meta = {}, {}, {"near_term": [], "holiday": [], "straddles": [], "status": "error"}

meta_by_pair = _game_meta(2026, current_leg)
holiday_set = set(meta.get("holiday", []))
floor_this_week = holiday_min_prob if current_leg in holiday_set else min_prob


# ---------------------------------------------------------------------------
# Shared render helpers
# ---------------------------------------------------------------------------

def _matchup_bits(pick, game_meta_pair):
    """(matchup_str, caption_str, spread_for_pick or None) for a pick."""
    g = ingest_lines.game_for_team(game_meta_pair, pick) if game_meta_pair else None
    if not g:
        return f"**{pick}{_rec(pick)}**", "⏳ game data not available yet", None
    away, home, m = g
    opp = home if pick == away else away
    loc = f"@ {opp}{_rec(opp)}" if pick == away else f"vs {opp}{_rec(opp)}"
    ha = "AWAY" if pick == away else "HOME"
    bits = []
    if m.get("kickoff_display"):
        bits.append(f"🗓 {m['kickoff_display']}")
    phrase = ingest_lines.describe_spread_for_pick(pick, home, away, m.get("spread_home"))
    if phrase:
        bits.append(phrase)
    if m.get("ml_home") is not None and m.get("ml_away") is not None:
        ml = m["ml_home"] if pick == home else m["ml_away"]
        bits.append(f"ML {ml:+d}")
    sp = None
    if m.get("spread_home") is not None:
        sp = m["spread_home"] if pick == home else -m["spread_home"]
    return (f"**{pick}{_rec(pick)}** {loc} · *{ha}*",
            " · ".join(bits) or "⏳ no line posted yet", sp)


def _rank_alternatives(leg_id, entry_idx, floor, top_n=6):
    """Viable teams for one entry/leg, by win prob desc; model pick always included."""
    entry = state["entries"][entry_idx]
    used = set(entry["used_teams"])
    bucket = state_mod.effective_bucket(entry, leg_id)
    cw = solver.DEFAULT_CONTRARIAN_BY_BUCKET.get(
        bucket, solver.DEFAULT_CONTRARIAN_BY_BUCKET.get(None, 0.6))
    leg_probs = probs.get(leg_id, {})
    if not leg_probs:
        return []
    top_p = max(leg_probs.values())
    cands = []
    for team, p in leg_probs.items():
        if p < floor or team in used:
            continue
        stacks = sorted(o for o in res if o != entry_idx and res.get(o, {}).get(leg_id) == team)
        cands.append({
            "team": team, "win_prob": p,
            "in_tx": team in sched.TXWEEK_POOL, "in_xmas": team in sched.XMASWEEK_POOL,
            "stacks_with": stacks,
            "is_rec": res.get(entry_idx, {}).get(leg_id) == team,
        })
    cands.sort(key=lambda c: -c["win_prob"])
    top = cands[:top_n]
    if not any(c["is_rec"] for c in top):
        rec = next((c for c in cands if c["is_rec"]), None)
        if rec:
            top.append(rec)
    return top


def render_alternatives(leg_id, entry_idx, floor, key_prefix):
    alts = _rank_alternatives(leg_id, entry_idx, floor)
    if not alts:
        st.caption(f"No alternatives above the {floor:.0%} floor.")
        return
    rows = []
    for a in alts:
        g = ingest_lines.game_for_team(meta_by_pair, a["team"]) if leg_id == current_leg else None
        if g:
            away_t, home_t, gm = g
            opp_t = home_t if a["team"] == away_t else away_t
            matchup = (f"@ {opp_t}{_rec(opp_t)}" if a["team"] == away_t
                       else f"vs {opp_t}{_rec(opp_t)}")
            sh = gm.get("spread_home")
            sp = (sh if a["team"] == home_t else -sh) if sh is not None else None
            spread_str = ("PK" if sp is not None and abs(sp) < 0.05
                          else f"{sp:+.1f}" if sp is not None else "—")
        else:
            matchup, spread_str = "—", "—"
        pool_tags = ("TX" if a["in_tx"] else "") + ("/XMAS" if a["in_xmas"] else "")
        fv = solver.future_value(a["team"])
        if fv >= 0.8:
            conserve = "🛑 hold"
        elif fv >= 0.35:
            conserve = "🤔 costly"
        else:
            conserve = "✅ burn-friendly"
        wt = data.WIN_TOTALS.get(a["team"], (None,))[0]
        rows.append({
            "Team": ("★ " if a["is_rec"] else "") + a["team"] + _rec(a["team"]),
            "Game": matchup, "Spread": spread_str,
            "Win%": f"{a['win_prob']:.1%}",
            "Win O/U": f"{wt:.1f}" if wt is not None else "—",
            "Conserve": conserve,
            "Pool": pool_tags.strip("/") or "—",
            "Stack": ",".join(a["stacks_with"]) or "—",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("★ model pick · Win O/U = season win total (DraftKings, June) — low O/U "
               "as a favorite = the burn-friendly spot · Conserve = season-long value "
               "of NOT burning the team now · Pool = holiday membership · "
               "Stack = other entry on same team")


def render_lock_controls(entry_idx, leg_id, pick, key_prefix):
    """Confirm-checkbox + lock button. Writes state and reruns."""
    c1, c2 = st.columns([1, 2])
    with c1:
        confirm = st.checkbox("Confirm", key=f"{key_prefix}_ok_{entry_idx}_{leg_id}_{pick}")
    with c2:
        if st.button(f"🔒 Lock {pick}", key=f"{key_prefix}_lock_{entry_idx}_{leg_id}",
                     type="primary", disabled=not confirm, width="stretch"):
            state_mod.record_pick(state, entry_idx, leg_id, pick, survived=True)
            state_mod.save_state(state)
            st.rerun()


def render_entry_card(entry_idx, compact=False, key_prefix="tw"):
    """This-week action card for one entry."""
    entry = state["entries"][entry_idx]
    bucket = entry.get("bucket") or "—"
    alive = entry["alive"]
    locked_team = entry["picks"].get(current_leg)
    pick = locked_team or res.get(entry_idx, {}).get(current_leg)

    with st.container(border=True):
        status = "🔒 LOCKED" if locked_team else ("▶ pick now" if alive else "❌ eliminated")
        st.markdown(f"#### {'🟢' if alive else '🔴'} Entry {entry_idx} · {bucket} · {status}")
        if not alive:
            st.caption("This entry has been eliminated.")
            return
        if not pick:
            st.warning("No pick clears the floor — lower `min_prob` in Advanced.")
            return
        headline, caption, sp = _matchup_bits(pick, meta_by_pair)
        p = probs.get(current_leg, {}).get(pick)
        hl, hr = st.columns([3, 1])
        with hl:
            st.markdown(f"### {headline}")
            st.caption(caption)
        with hr:
            st.metric("Win prob", f"{p:.1%}" if p is not None else "—")
        if sp is not None and sp > 0.5:
            st.warning(f"⚠ Underdog by {sp:.1f} — verify before locking.")
        if not locked_team:
            render_lock_controls(entry_idx, current_leg, pick, key_prefix)
        if not compact:
            with st.expander("📊 Other options"):
                render_alternatives(current_leg, entry_idx, floor_this_week, key_prefix)


# ---------------------------------------------------------------------------
# Bracket-style roadmap (HTML)
# ---------------------------------------------------------------------------

_NODE_STYLES = {
    # status: (border, background, opacity)
    "locked":  ("2px solid #2ecc71", "rgba(46,204,113,.10)", "1"),
    "current": ("3px solid #e8b339", "rgba(232,179,57,.14)", "1"),      # gold = act now
    "planned": ("1.5px solid #5c6478", "rgba(92,100,120,.10)", ".95"),
    "holiday": ("2px solid #8b5cf6", "rgba(139,92,246,.12)", "1"),      # violet = holiday
    "gap":     ("1px dashed #5c647866", "transparent", ".6"),
}


_BUCKET_SHORT = {"chalk": "chalk", "contrarian": "contrarian", "conservation": "conserve", "neutral": "neutral"}
_BUCKET_COLOR = {"chalk": "#21a366", "contrarian": "#c0392b", "conservation": "#d4a017", "neutral": "#8b93a7"}


def _roadmap_node(label, team, prob, status, icon="", bucket=None):
    border, bg, op = _NODE_STYLES[status]
    team_line = f"<div style='font-size:1.05rem;font-weight:700'>{team}</div>" if team else ""
    prob_line = f"<div style='font-size:.75rem;opacity:.75'>{prob}</div>" if prob else ""
    tag_line = ""
    if bucket in _BUCKET_SHORT:
        tag_line = (
            f"<div style='font-size:.6rem;font-weight:700;text-transform:uppercase;"
            f"letter-spacing:.03em;color:{_BUCKET_COLOR[bucket]}'>"
            f"{_BUCKET_SHORT[bucket]}</div>"
        )
    return (
        f"<div style='border:{border};background:{bg};opacity:{op};"
        f"border-radius:10px;padding:6px 10px;min-width:64px;text-align:center'>"
        f"<div style='font-size:.7rem;opacity:.8;white-space:nowrap'>{icon}{label}</div>"
        f"{team_line}{prob_line}{tag_line}</div>"
    )


def render_roadmap(entry_idx, res_x=None, probs_x=None, state_x=None, meta_x=None,
                   show_legend=True, expand=False):
    """Horizontal bracket: locked ✓ → current → planned → ⋯ → 🎄 → ⋯ → 🎁 → ⋯

    Accepts alternate (res, probs, state, meta) so what-if simulations can be
    drawn with the same renderer. Defaults to the live solve.

    expand=True renders EVERY week as its own node instead of collapsing
    out-of-scope stretches into a "⋯" gap — unplanned weeks show their
    strategy tag (if a per-week bucket is set) with a "·" team placeholder.
    """
    res_x = res_x if res_x is not None else res
    probs_x = probs_x if probs_x is not None else probs
    state_x = state_x if state_x is not None else state
    meta_x = meta_x if meta_x is not None else meta

    entry = state_x["entries"][entry_idx]
    picks = entry["picks"]
    in_scope = set(meta_x.get("near_term", [])) | set(meta_x.get("holiday", []))

    nodes = []
    gap_run = []

    def flush_gap():
        if gap_run:
            label = f"{gap_run[0]}–{gap_run[-1]}" if len(gap_run) > 1 else gap_run[0]
            nodes.append(_roadmap_node(label, "⋯", "", "gap"))
            gap_run.clear()

    for lid in loaded_legs:
        locked_team = picks.get(lid)
        planned_team = res_x.get(entry_idx, {}).get(lid)
        is_holiday = lid in sched.HOLIDAY_WEEKS
        icon = "🎄 " if lid == "TXWEEK" else ("🎁 " if lid == "XMASWEEK" else "")

        bkt = state_mod.effective_bucket(entry, lid)
        # Holiday legs are bucket-exempt in the solver, so don't tag them.
        node_bkt = None if is_holiday else bkt

        if locked_team:
            flush_gap()
            nodes.append(_roadmap_node(lid, f"✓ {locked_team}", "locked", "locked", icon,
                                       bucket=node_bkt))
        elif lid == current_leg and planned_team:
            flush_gap()
            p = probs_x.get(lid, {}).get(planned_team)
            nodes.append(_roadmap_node(
                lid, planned_team, f"{p:.0%}" if p else "", "current", icon, bucket=node_bkt))
        elif is_holiday and planned_team:
            flush_gap()
            p = probs_x.get(lid, {}).get(planned_team)
            nodes.append(_roadmap_node(
                lid, planned_team, f"{p:.0%} reserve" if p else "reserve", "holiday", icon))
        elif lid in in_scope and planned_team:
            flush_gap()
            p = probs_x.get(lid, {}).get(planned_team)
            nodes.append(_roadmap_node(
                lid, planned_team, f"{p:.0%} plan" if p else "plan", "planned", icon,
                bucket=node_bkt))
        elif expand:
            # Expanded view: every week is a node. No planned pick yet —
            # show the strategy tag so a mapped-out season reads at a glance.
            status = "holiday" if is_holiday else "gap"
            nodes.append(_roadmap_node(lid, "·", "", status, icon, bucket=node_bkt))
        else:
            gap_run.append(lid)
    flush_gap()

    # Horizontal scroll strip — swipeable on phones, tidy at horizon=17 on
    # desktop. Inline styles on our own div only; no Streamlit internals
    # touched, so this cannot affect the rest of the page.
    arrow = "<div style='opacity:.45;font-size:1.1rem;flex:0 0 auto'>→</div>"
    html = (
        "<div style='display:flex;flex-wrap:nowrap;overflow-x:auto;"
        "align-items:center;gap:6px;padding:6px 2px 12px'>"
        + arrow.join(f"<div style='flex:0 0 auto'>{n}</div>" for n in nodes)
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)
    if show_legend:
        st.caption(
            "✓ locked · gold = this week (lock it) · gray = planned (re-solved weekly) · "
            "violet = holiday reservation · ⋯ = solved later — **edit any node in "
            "🔀 Plan / edit any week below**"
        )


# ---------------------------------------------------------------------------
# What-if: override this week's pick, re-solve, show the ripple
# ---------------------------------------------------------------------------

def run_what_if(entry_idx, override_team, leg_id):
    """Sandbox solve with `override_team` locked for this entry in `leg_id`.

    Returns (sim_res, sim_probs, sim_meta, sim_state). Never touches real state.
    """
    sim_state = copy.deepcopy(state)
    state_mod.record_pick(sim_state, entry_idx, leg_id, override_team, survived=True)
    sim_res, sim_probs, sim_meta = solver.solve(
        sim_state, horizon=effective_horizon, min_prob=min_prob,
        holiday_min_prob=holiday_min_prob,
        future_value_weight=future_value_weight, endgame=endgame,
    )
    return sim_res, sim_probs, sim_meta, sim_state


def render_what_if(entry_idx, leg_id):
    """Selectbox of alternatives for `leg_id`; on override, show the re-solved
    plan vs current. Works for the current week and any future week alike."""
    entry = state["entries"][entry_idx]
    if leg_id in entry["picks"]:
        st.caption(f"{leg_id} is locked — unlock it above to edit.")
        return
    leg_floor = holiday_min_prob if leg_id in holiday_set else min_prob
    model_pick = res.get(entry_idx, {}).get(leg_id)
    alts = _rank_alternatives(leg_id, entry_idx, leg_floor, top_n=12)
    if not alts:
        st.caption(f"No viable teams above the {leg_floor:.0%} floor for {leg_id}. "
                   "Lower min_prob in Advanced to see candidates.")
        return

    team_options = [a["team"] for a in alts]
    labels = {}
    for a in alts:
        tag = " ★ model pick" if a["is_rec"] else ""
        pool_bits = ("TX" if a["in_tx"] else "") + ("/XMAS" if a["in_xmas"] else "")
        pool_note = f" · burns {pool_bits.strip('/')}" if pool_bits else ""
        wt = data.WIN_TOTALS.get(a["team"], (None,))[0]
        wt_note = f" · {wt:.1f} O/U" if wt is not None else ""
        labels[a["team"]] = (f"{a['team']}{_rec(a['team'])} — "
                             f"{a['win_prob']:.0%}{wt_note}{pool_note}{tag}")

    default_idx = team_options.index(model_pick) if model_pick in team_options else 0
    choice = st.selectbox(
        "Pick to explore", team_options, index=default_idx,
        format_func=lambda t: labels[t],
        key=f"whatif_team_{entry_idx}_{leg_id}",
    )

    if choice == model_pick:
        st.caption("That's the model pick — the roadmap above already shows this plan. "
                   "Choose a different team to see the ripple.")
        return

    with st.spinner("Re-solving season plan around your pick…"):
        sim_res, sim_probs, sim_meta, sim_state = run_what_if(entry_idx, choice, leg_id)

    if sim_meta["status"] != "Optimal":
        st.error(
            f"Solver status with {choice} locked: {sim_meta['status']}. This override "
            "likely breaks a hard constraint (e.g. leaves no viable holiday pool team). "
            "Strong signal NOT to make this pick."
        )
        return

    # --- headline: the chosen week's prob delta ---
    p_model = probs.get(leg_id, {}).get(model_pick)
    p_choice = probs.get(leg_id, {}).get(choice)
    m1, m2 = st.columns(2)
    m1.metric(f"Model pick · {model_pick}",
              f"{p_model:.1%}" if p_model is not None else "—")
    m2.metric(f"Your pick · {choice}",
              f"{p_choice:.1%}" if p_choice is not None else "—",
              delta=(f"{(p_choice - p_model):+.1%}"
                     if p_model is not None and p_choice is not None else None))

    # --- stacking check against the other entry ---
    others_on_choice = [
        o for o in entry_ids
        if o != entry_idx
        and (state["entries"][o]["picks"].get(leg_id) == choice
             or sim_res.get(o, {}).get(leg_id) == choice)
    ]
    if others_on_choice:
        st.error(
            f"⚠ Entry {', '.join(others_on_choice)} is also on {choice} in {leg_id} — "
            "this override stacks both entries on one game."
        )

    # --- diff table: this entry's plan across all other legs, current vs override ---
    scope_legs = [lid for lid in loaded_legs
                  if lid in (set(meta.get("near_term", [])) | holiday_set)
                  and lid != leg_id]
    diff_rows = []
    for lid in scope_legs:
        before = res.get(entry_idx, {}).get(lid)
        after = sim_res.get(entry_idx, {}).get(lid)
        pb = probs.get(lid, {}).get(before) if before else None
        pa = sim_probs.get(lid, {}).get(after) if after else None
        changed = before != after
        diff_rows.append({
            "Leg": lid,
            "Current plan": f"{before} ({pb:.0%})" if before else "—",
            "With your pick": f"{after} ({pa:.0%})" if after else "—",
            "Changed": "🔄" if changed else "",
        })
    if diff_rows:
        st.markdown("**How your future plan shifts**")
        st.dataframe(pd.DataFrame(diff_rows), hide_index=True, width="stretch")

    # --- other entry ripple ---
    ripple = []
    for o in entry_ids:
        if o == entry_idx:
            continue
        for lid in [leg_id] + scope_legs:
            b = res.get(o, {}).get(lid)
            a = sim_res.get(o, {}).get(lid)
            if b != a and lid not in state["entries"][o]["picks"]:
                ripple.append(f"Entry {o} {lid}: {b} → {a}")
    if ripple:
        st.info("Portfolio ripple (decorrelation re-balances the other entry): "
                + " · ".join(ripple))

    # --- override roadmap ---
    st.markdown(f"**Roadmap with {choice} locked in {leg_id}**")
    render_roadmap(entry_idx, sim_res, sim_probs, sim_state, sim_meta,
                   show_legend=False)

    # --- lock the override ---
    if leg_id == current_leg:
        st.markdown("**Lock this override instead of the model pick**")
    else:
        st.markdown(f"**Pin {choice} for {leg_id}** — the solver will plan every "
                    "other week around it. Unlock anytime before it's played.")
    render_lock_controls(entry_idx, leg_id, choice,
                         key_prefix=f"whatif{entry_idx}_{leg_id}")


# ---------------------------------------------------------------------------
# Header strip
# ---------------------------------------------------------------------------

alive_n = sum(1 for e in state["entries"].values() if e["alive"])
locked_this_week = sum(1 for e in entry_ids if current_leg in state["entries"][e]["picks"])
h1, h2, h3 = st.columns(3)
h1.metric("Contest Week", current_leg)
h2.metric("Entries alive", f"{alive_n}/{len(entry_ids)}")
h3.metric("Locked this week", f"{locked_this_week}/{alive_n}")

if solver_error:
    st.error(f"Solver failed: {solver_error}")
elif meta["status"] != "Optimal":
    st.warning(f"Solver status: {meta['status']}")


# ---------------------------------------------------------------------------
# Tabs — entry-first
# ---------------------------------------------------------------------------

tab_labels = (["🏟 Board", "🎯 This Week"]
              + [f"Entry {e}" for e in entry_ids]
              + ["📈 Market", "🔧 Data & Tools"])
all_tabs = st.tabs(tab_labels)
tab_board = all_tabs[0]
tab_week = all_tabs[1]
entry_tabs = all_tabs[2:2 + len(entry_ids)]
tab_market = all_tabs[2 + len(entry_ids)]
tab_tools = all_tabs[3 + len(entry_ids)]


# ----- 🏟 Board (custom HTML dashboard) ---------------------------------------

with tab_board:
    from survivor import board as board_mod
    import streamlit.components.v1 as components

    board_html = board_mod.build_board(
        state, entry_ids, res, probs, meta, current_leg,
        loaded_legs, meta_by_pair, RECORDS,
    )
    # Height scales with entry count; the iframe scrolls internally past that.
    components.html(board_html, height=760 + 40 * max(0, len(entry_ids) - 2),
                    scrolling=True)


# ----- 🎯 This Week ----------------------------------------------------------

with tab_week:
    st.caption(
        f"Your action for **{current_leg}**: check each card, confirm, lock. "
        "Details and the season roadmap live in each entry's own tab."
    )

    with st.expander("📖 Strategy guide — what each bucket does & how it's built"):
        st.markdown(
            """
**Three strategy buckets.** Each entry has a default bucket (sidebar), and you
can override it per week on the entry's tab (🎛 Per-week strategy).

- 🟢 **Chalk** — take the safest favorite every week. Maximizes raw survival,
  barely conserves. Your *stay-alive* entry.
- 🔴 **Contrarian** — deliberately fade the popular/obvious pick so your entries
  fail **independently** (and you diverge from the public field). Trades a few
  points of weekly safety for decorrelation — if a chalk-killing upset lands,
  this entry is positioned to survive it.
- 🟡 **Conservation** — hoard strong teams and holiday-pool teams; spend
  **low-win-total teams early** while they're favorites (e.g. a 5.5-win team
  laying −175 at home). Builds a deeper roster for the back half and the two
  holiday Contest Weeks.

**How the model picks.** A mixed-integer optimizer (PuLP/HiGHS) maximizes, across
every planned week, the sum over your picks of

&nbsp;&nbsp;&nbsp;`log(win probability)  −  contrarian × popularity  −  conservation × future-value`

subject to hard rules: exactly one team per week, **no team reused all season**,
and **at least one pool team reserved** for Thanksgiving & Christmas (Rules 8/9).
Win probability blends our Elo model with DraftKings moneylines. The bucket sets
the *contrarian* and *conservation* weights for that week — so switching a week's
bucket literally re-weights that week's objective and can change the pick.

**Why 2 entries + buckets?** One upset shouldn't kill your whole portfolio.
Running chalk + contrarian keeps one entry maximally safe while the other stays
decorrelated, so you're more likely to arrive at the holidays with *both* entries
alive holding *different* teams — the position that lets you hedge.
"""
        )

    cols = st.columns(len(entry_ids))
    for col, e in zip(cols, entry_ids):
        with col:
            render_entry_card(e, compact=False, key_prefix="tw")

    # cross-entry stack warning
    week_picks = [state["entries"][e]["picks"].get(current_leg)
                  or res.get(e, {}).get(current_leg) for e in entry_ids]
    week_picks = [t for t in week_picks if t]
    if len(week_picks) > 1 and len(set(week_picks)) < len(week_picks):
        st.error(
            f"⚠ Both entries are on **{week_picks[0]}** this week — one upset kills "
            "both. That defeats the decorrelation thesis; check the alternatives."
        )


# ----- Entry tabs -------------------------------------------------------------

for tab, e in zip(entry_tabs, entry_ids):
    with tab:
        entry = state["entries"][e]
        bucket = entry.get("bucket") or "—"

        st.subheader("Season roadmap")
        # Auto-expand the map when this entry has strategy set for weeks the
        # solver isn't planning yet — otherwise those overrides would be
        # hidden inside a collapsed "⋯" gap.
        scope_now = set(meta.get("near_term", [])) | holiday_set
        has_hidden_overrides = any(
            lid not in scope_now for lid in entry.get("leg_buckets", {})
        )
        expand_map = st.toggle(
            "Expand all weeks", value=has_hidden_overrides, key=f"expand_map_{e}",
            help="Show every week as its own node. Weeks without a planned pick "
                 "show a · placeholder plus your strategy tag. To fill picks in, "
                 "raise Horizon in the sidebar (Advanced) — up to the full season.",
        )
        render_roadmap(e, expand=expand_map)

        with st.expander("🎛 Per-week strategy — override the bucket for any week"):
            st.caption(
                "Every week defaults to this entry's bucket (set in the sidebar). "
                "Override any upcoming week here — e.g. contrarian in W1, "
                "conservation in W2, contrarian again in W3. Locked weeks can't change. "
                "To see planned PICKS for far-out weeks on the map, raise Horizon "
                "(sidebar → Advanced) up to 17 = whole season."
            )
            default_bkt = entry.get("bucket") or "—"
            st.markdown(f"Entry default: **{default_bkt}**  ·  color key: "
                        f"<span style='color:#21a366;font-weight:700'>CHALK</span> · "
                        f"<span style='color:#c0392b;font-weight:700'>CONTRARIAN</span> · "
                        f"<span style='color:#d4a017;font-weight:700'>CONSERVE</span>",
                        unsafe_allow_html=True)
            leg_buckets = entry.get("leg_buckets", {})
            start = loaded_legs.index(current_leg) if current_leg in loaded_legs else 0
            # Non-holiday upcoming legs (buckets don't affect holiday weeks).
            editable = [lid for lid in loaded_legs[start:] if lid not in sched.HOLIDAY_WEEKS]
            for lid in editable:
                is_locked = lid in entry["picks"]
                opts = ["(default)", "chalk", "contrarian", "conservation"]
                cur = leg_buckets.get(lid)
                idx = opts.index(cur) if cur in opts else 0
                lc, rc = st.columns([1, 3])
                lc.markdown(f"**{lid}**" + (" 🔒" if is_locked else ""))
                sel = rc.selectbox(
                    "bucket", opts, index=idx, key=f"legbkt_{e}_{lid}",
                    label_visibility="collapsed", disabled=is_locked,
                )
                new_val = None if sel == "(default)" else sel
                if not is_locked and new_val != cur:
                    state_mod.set_leg_bucket(state, e, lid, new_val)
                    state_mod.save_state(state)
                    st.rerun()

        st.divider()
        st.subheader(f"This week ({current_leg})")
        render_entry_card(e, compact=False, key_prefix=f"ent{e}")

        st.divider()
        st.subheader("🔀 Plan / edit any week")
        st.caption(
            "Pick a week, explore overriding the model there, and watch the whole "
            "season plan re-solve around it. Nothing is saved until you lock. "
            "Locking a future week PINS it — the model plans everything else "
            "around your pin, and you can unlock it anytime before kickoff."
        )

        # Week selector: label each week with its current disposition so the
        # dropdown doubles as a season summary.
        def _week_label(lid, _entry=entry, _e=e):
            icon = "🎄 " if lid == "TXWEEK" else ("🎁 " if lid == "XMASWEEK" else "")
            locked_t = _entry["picks"].get(lid)
            if locked_t:
                return f"{icon}{lid} — 🔒 {locked_t}"
            planned_t = res.get(_e, {}).get(lid)
            bkt = state_mod.effective_bucket(_entry, lid) or "—"
            if planned_t:
                p = probs.get(lid, {}).get(planned_t)
                p_str = f" ({p:.0%})" if p is not None else ""
                cur = " ← this week" if lid == current_leg else ""
                return f"{icon}{lid} — {planned_t}{p_str} · {bkt}{cur}"
            return f"{icon}{lid} — no pick above floor · {bkt}"

        editable_legs = [lid for lid in loaded_legs]
        default_leg_idx = editable_legs.index(current_leg) if current_leg in editable_legs else 0
        sel_leg = st.selectbox(
            "Week to plan", editable_legs, index=default_leg_idx,
            format_func=_week_label, key=f"planweek_{e}",
        )

        if sel_leg in entry["picks"]:
            locked_t = entry["picks"][sel_leg]
            st.markdown(f"**{sel_leg} is locked on `{locked_t}`.**")
            u1, u2 = st.columns([1, 2])
            with u1:
                confirm_unlock = st.checkbox("Confirm unlock", key=f"unlock_ok_{e}_{sel_leg}")
            with u2:
                if st.button(f"🔓 Unlock {sel_leg} ({locked_t})",
                             key=f"unlock_{e}_{sel_leg}", disabled=not confirm_unlock):
                    state_mod.unlock_pick(state, e, sel_leg)
                    state_mod.save_state(state)
                    st.rerun()
            st.caption("Unlock frees the team for other weeks and lets the solver "
                       "re-plan this week. Don't unlock a pick already submitted "
                       "to Circa unless you're changing it there too.")
        else:
            render_what_if(e, sel_leg)

        st.divider()
        st.subheader("Roster status")
        used = entry["used_teams"]
        rc1, rc2 = st.columns(2)
        with rc1:
            st.markdown("**Teams used** "
                        + (" ".join(f"~~`{t}`~~" for t in used) if used else "*none yet*"))
        with rc2:
            for hw, pool, icon in [("TXWEEK", sched.TXWEEK_POOL, "🎄"),
                                   ("XMASWEEK", sched.XMASWEEK_POOL, "🎁")]:
                remaining = sorted(pool - set(used))
                locked_h = entry["picks"].get(hw)
                if locked_h:
                    st.markdown(f"{icon} **{hw}**: locked `{locked_h}`")
                elif not remaining:
                    st.markdown(f"{icon} **{hw}**: ⚠ **EXHAUSTED**")
                else:
                    st.markdown(f"{icon} **{hw}** ({len(remaining)} left): "
                                + " ".join(f"`{t}`" for t in remaining))


# ----- 📈 Market ---------------------------------------------------------------

with tab_market:
    st.caption(
        "**Line movement**: where the line moved since open — the market's verdict "
        "on where money is landing. **Splits**: bets% = tickets (the public), "
        "handle% = money (the size). Handle ≫ bets = sharp-money signature."
    )
    mkt_leg = st.selectbox("Leg", loaded_legs,
                           index=loaded_legs.index(current_leg), key="market_leg")
    mkt = _game_meta(2026, mkt_leg) if mkt_leg in ingest_lines.LEG_TO_ESPN_WEEK else {}

    st.subheader("Line movement (open → current)")
    rows = []
    for (away, home), m in mkt.items():
        sp_o, sp_c = m.get("spread_home_open"), m.get("spread_home")
        mlh_o, mlh_c = m.get("ml_home_open"), m.get("ml_home")
        mla_o, mla_c = m.get("ml_away_open"), m.get("ml_away")
        move = []
        if sp_o is not None and sp_c is not None and sp_o != sp_c:
            move.append(f"spread → {home if sp_c < sp_o else away}")
        if mlh_o is not None and mlh_c is not None and mlh_c != mlh_o:
            move.append(f"ML → {home if mlh_c < mlh_o else away}")
        rows.append({
            "Game": f"{away} @ {home}",
            "Kickoff": m.get("kickoff_display") or "—",
            "Spread (home)": (f"{sp_o:+.1f} → {sp_c:+.1f}"
                              if sp_o is not None and sp_c is not None
                              else (f"{sp_c:+.1f}" if sp_c is not None else "—")),
            "ML home": (f"{mlh_o:+d} → {mlh_c:+d}"
                        if mlh_o is not None and mlh_c is not None
                        else (f"{mlh_c:+d}" if mlh_c is not None else "—")),
            "ML away": (f"{mla_o:+d} → {mla_c:+d}"
                        if mla_o is not None and mla_c is not None
                        else (f"{mla_c:+d}" if mla_c is not None else "—")),
            "Money moving toward": ", ".join(move) or "—",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Home spread more negative or ML shortening = money on that side. "
                   "Movement AGAINST the public split below = reverse line movement, "
                   "the strongest sharp signal.")
    else:
        st.info("No lines posted for this leg yet.")

    st.divider()
    st.subheader("Betting splits — bets% vs handle% (VSiN / DraftKings)")
    if st.button("Fetch splits from VSiN", type="primary"):
        with st.spinner("Scraping VSiN…"):
            st.session_state["vsin_splits"] = ingest_splits.fetch_splits()
    if "vsin_splits" in st.session_state:
        games, note = st.session_state["vsin_splits"]
        if not games:
            st.info(note)
        else:
            st.success(note)
            srows = []
            for g in games:
                srows.append({
                    "Game": f"{g['away']} @ {g['home']}",
                    "Spread bets a/h": f"{g['spread_bets_away']}% / {g['spread_bets_home']}%",
                    "Spread handle a/h": f"{g['spread_handle_away']}% / {g['spread_handle_home']}%",
                    "Spread signal": (ingest_splits.sharp_signal(g['spread_bets_away'], g['spread_handle_away'])
                                      or ingest_splits.sharp_signal(g['spread_bets_home'], g['spread_handle_home'])),
                    "ML bets a/h": f"{g['ml_bets_away']}% / {g['ml_bets_home']}%",
                    "ML handle a/h": f"{g['ml_handle_away']}% / {g['ml_handle_home']}%",
                    "ML signal": (ingest_splits.sharp_signal(g['ml_bets_away'], g['ml_handle_away'])
                                  or ingest_splits.sharp_signal(g['ml_bets_home'], g['ml_handle_home'])),
                })
            st.dataframe(pd.DataFrame(srows), hide_index=True, width="stretch")
            st.caption("💰 sharp side? = handle ≥15pts above tickets · 🎫 public side = "
                       "tickets above handle. One book (DK); directional, not gospel.")
    else:
        st.caption("Offseason note: VSiN's NFL table populates as game week approaches.")


# ----- 🔧 Data & Tools ----------------------------------------------------------

with tab_tools:

    with st.expander("📋 Pools & availability", expanded=False):
        pool_leg = st.selectbox("Contest Week", loaded_legs, key="tools_pool_leg")
        pool = sorted(sched.teams_in_week(pool_leg))
        st.markdown(f"**Full pool ({len(pool)}):** " + " ".join(f"`{t}`" for t in pool))
        for e in entry_ids:
            entry = state["entries"][e]
            used = set(entry["used_teams"])
            avail = [t for t in pool if t not in used]
            locked_p = entry["picks"].get(pool_leg)
            if locked_p:
                st.markdown(f"**Entry {e}**: 🔒 locked `{locked_p}`")
            elif not avail:
                st.markdown(f"**Entry {e}**: ⚠ EXHAUSTED")
            else:
                st.markdown(f"**Entry {e}** ({len(avail)}/{len(pool)} available): "
                            + " ".join(f"`{t}`" for t in avail))

    with st.expander("💵 Ingest moneylines (feeds the solver's market blend)"):
        line_leg = st.selectbox("Leg", loaded_legs,
                                index=loaded_legs.index(current_leg), key="tools_line_leg")
        if st.button(f"Ingest DraftKings lines for {line_leg}"):
            with st.spinner("Fetching…"):
                applied, skipped = ingest_lines.ingest_lines_for_leg(state, line_leg)
            st.success(f"Wrote {len(applied)} lines; {len(skipped)} games had none posted.")
            st.rerun()
        overrides = state.get("leg_overrides", {}).get(line_leg, {}).get("lines", {})
        if overrides:
            st.caption(f"{len(overrides)} stored overrides for {line_leg}.")

    with st.expander("🏁 Verify results (after games complete)"):
        ver_leg = st.selectbox("Leg", loaded_legs,
                               index=loaded_legs.index(current_leg), key="tools_ver_leg")
        if st.button(f"Verify {ver_leg} from ESPN finals"):
            with st.spinner("Checking scores…"):
                results, _ = ingest_results.verify_leg(state, ver_leg)
            if not results:
                st.info("No picks locked for this leg.")
            for e, team, status_str, info in results:
                score = ""
                if info and info.get("home_score") is not None:
                    score = f" — {info['away']} {info['away_score']} @ {info['home']} {info['home_score']}"
                st.write(f"Entry {e}: {team} → **{status_str}**{score}")
            st.rerun()

    with st.expander("🩹 Injuries (ESPN feed)"):
        sev = st.radio("Severity", ["high", "all"], horizontal=True, key="tools_inj_sev")
        if st.button("Fetch injuries"):
            with st.spinner("Fetching…"):
                st.session_state["inj_payload"] = ingest_injuries.fetch_injuries()
        if "inj_payload" in st.session_state:
            by_team = ingest_injuries.parse_injuries(st.session_state["inj_payload"], severity=sev)
            teams_sorted = sorted(by_team, key=lambda t: -ingest_injuries.team_alert_score(by_team[t]))
            if not teams_sorted:
                st.info(f"No {sev}-severity injuries right now.")
            for abbr in teams_sorted[:10]:
                rows_i = ingest_injuries.sort_by_priority(by_team[abbr])
                st.markdown(f"**{abbr}** — "
                            + "; ".join(f"{r['position']} {r['name']} ({r['status']})"
                                        for r in rows_i[:4]))
        st.divider()
        st.markdown("**Manual Elo nudge**")
        n1, n2, n3 = st.columns([1, 1, 2])
        nudge_team = n1.selectbox("Team", sorted(data.BASE_ELO), key="tools_nudge_team")
        nudge_delta = n2.number_input("Δ Elo", -100, 100, 0, 5, key="tools_nudge_delta")
        nudge_note = n3.text_input("Note", key="tools_nudge_note")
        if st.button("Apply nudge") and nudge_delta != 0:
            state_mod.adjust_strength(state, nudge_team, float(nudge_delta), note=nudge_note or None)
            state_mod.save_state(state)
            st.success(f"{nudge_team} {nudge_delta:+d} Elo "
                       f"(cumulative {state['elo_adjustments'].get(nudge_team, 0):+.0f})")

    with st.expander("✅ Integrity check"):
        if st.button("Run check"):
            failures = []
            errs = sched.validate()
            failures.extend(f"schedule: {x}" for x in errs)
            ph = [t for t, (_, p_) in data.WIN_TOTALS.items() if p_ == "PLACEHOLDER"]
            if ph:
                failures.append(f"data: placeholders remain: {ph}")
            if meta["status"] != "Optimal":
                failures.append(f"solver: {meta['status']}")
            for e in entry_ids:
                entry = state["entries"][e]
                if not entry["alive"]:
                    continue
                used = set(entry["used_teams"])
                for hw, pool_h in [("TXWEEK", sched.TXWEEK_POOL), ("XMASWEEK", sched.XMASWEEK_POOL)]:
                    if hw not in entry["picks"] and not (pool_h - used):
                        failures.append(f"roster: entry {e} exhausted {hw}")
            if failures:
                for f_ in failures:
                    st.error(f_)
            else:
                st.success("All checks passed: schedule pools ✓ · no placeholders ✓ · "
                           "solver Optimal ✓ · holiday rosters ✓")

    with st.expander("🗑 Reset season state"):
        st.warning("Deletes season_state.json — all picks, buckets, nudges, lines.")
        if st.checkbox("I understand", key="tools_reset_ok"):
            if st.button("Reset now", type="primary"):
                if os.path.exists(state_mod.STATE_PATH):
                    os.remove(state_mod.STATE_PATH)
                st.rerun()

st.divider()
st.caption("CLI mirror: `python -m survivor [status|forecast|pick|lines|verify|injuries|check]` — "
           "UI and CLI share season_state.json.")
