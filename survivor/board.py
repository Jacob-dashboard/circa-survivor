"""
Circa Survivor 2026 — The Board
================================
A fully custom-designed HTML dashboard rendered inside the Streamlit app via
components.html. This is the "aesthetic layer": everything here is read-only
display built from the live solve; actions (lock/unlock/what-if) stay on the
native tabs.

Why an embedded HTML page instead of a separate site: free static hosts
(GitHub Pages) require a public repo — which would publish the picks to the
same field we're competing against — and free app hosts add accounts, sleep
rules, and a rewrite. Embedding gives 100% design freedom with the hosting,
auth, and live data we already have.

Everything is self-contained (inline CSS, no external requests except the
Inter font) and theme-matched to .streamlit/config.toml: navy #0b0f19,
gold #e8b339, violet holidays.
"""
from . import data
from . import schedule as sched
from . import state as state_mod


GOLD = "#e8b339"
VIOLET = "#8b5cf6"
GREEN = "#2ecc71"
RED = "#ef4444"
BG = "#0b0f19"
CARD = "#121828"
LINE = "rgba(232,179,57,.16)"
MUTED = "#8b93a7"

_BUCKET_CHIP = {
    "chalk":        ("CHALK", GREEN),
    "contrarian":   ("CONTRARIAN", RED),
    "conservation": ("CONSERVE", "#14b8a6"),
    None:           ("NO BUCKET", MUTED),
}


def _rec_str(records, team):
    r = records.get(team)
    return f"&nbsp;<span class='rec'>({r['summary']})</span>" if r else ""


def _matchup_block(entry_idx, pick, probs, leg, game_meta, records, locked):
    """The big this-week card for one entry."""
    p = probs.get(leg, {}).get(pick)
    p_str = f"{p*100:.1f}%" if p is not None else "—"
    p_pct = max(0, min(100, (p or 0) * 100))

    opp_line, detail_line, dog_warn = "", "", ""
    if game_meta:
        game = None
        for (away, home), m in game_meta.items():
            if pick in (away, home):
                game = (away, home, m)
                break
        if game:
            away, home, m = game
            opp = home if pick == away else away
            vs = "@" if pick == away else "vs"
            ha = "AWAY" if pick == away else "HOME"
            opp_line = (f"<span class='vs'>{vs}</span> {opp}{_rec_str(records, opp)} "
                        f"<span class='ha'>{ha}</span>")
            bits = []
            if m.get("kickoff_display"):
                bits.append(m["kickoff_display"])
            sh = m.get("spread_home")
            if sh is not None:
                sp = sh if pick == home else -sh
                if abs(sp) < 0.05:
                    bits.append("PK")
                else:
                    bits.append(f"{pick} {sp:+.1f}")
                if sp > 0.5:
                    dog_warn = "<div class='warn'>⚠ underdog — verify before locking</div>"
            ml = m.get("ml_home") if pick == home else m.get("ml_away")
            if ml is not None:
                bits.append(f"ML {ml:+d}")
            detail_line = " · ".join(bits)

    status = ("<span class='pill lock'>🔒 LOCKED</span>" if locked
              else "<span class='pill act'>ACT — pick now</span>")
    wt = data.WIN_TOTALS.get(pick, (None,))[0]
    wt_str = f"{wt:.1f} O/U" if wt is not None else ""

    return f"""
    <div class="matchup">
      <div class="mu-top">{status}<span class="ou">{wt_str}</span></div>
      <div class="mu-team">{pick}{_rec_str(records, pick)} {opp_line}</div>
      <div class="mu-detail">{detail_line or "line not posted yet"}</div>
      <div class="probwrap">
        <div class="probbar"><div class="probfill" style="width:{p_pct:.0f}%"></div></div>
        <div class="probnum">{p_str}</div>
      </div>
      {dog_warn}
    </div>"""


def _rail(entry, entry_idx, res, probs, current_leg, loaded_legs):
    """Season roadmap rail: every leg as a compact tile."""
    tiles = []
    for lid in loaded_legs:
        locked_team = entry["picks"].get(lid)
        planned = res.get(entry_idx, {}).get(lid)
        is_hol = lid in sched.HOLIDAY_WEEKS
        icon = "🎄" if lid == "TXWEEK" else ("🎁" if lid == "XMASWEEK" else "")
        bkt = state_mod.effective_bucket(entry, lid)
        chip, chip_color = _BUCKET_CHIP.get(bkt, _BUCKET_CHIP[None])

        if locked_team:
            cls, team, sub = "locked", f"✓ {locked_team}", "locked"
        elif lid == current_leg and planned:
            p = probs.get(lid, {}).get(planned)
            cls, team, sub = "now", planned, f"{p*100:.0f}%" if p else ""
        elif is_hol and planned:
            p = probs.get(lid, {}).get(planned)
            cls, team, sub = "hol", planned, f"{p*100:.0f}%" if p else ""
        elif planned:
            p = probs.get(lid, {}).get(planned)
            cls, team, sub = "plan", planned, f"{p*100:.0f}%" if p else ""
        else:
            cls, team, sub = "gap", "·", ""

        chip_html = (f"<div class='tile-chip' style='color:{chip_color}'>{chip}</div>"
                     if not is_hol and bkt else "")
        tiles.append(
            f"<div class='tile {cls}'>"
            f"<div class='tile-week'>{icon}{lid}</div>"
            f"<div class='tile-team'>{team}</div>"
            f"<div class='tile-sub'>{sub}</div>"
            f"{chip_html}"
            f"</div>"
        )
    return "<div class='rail'>" + "".join(tiles) + "</div>"


def _holiday_chips(entry):
    used = set(entry["used_teams"])
    out = []
    for hw, pool, icon, color in [
        ("TXWEEK", sched.TXWEEK_POOL, "🎄", VIOLET),
        ("XMASWEEK", sched.XMASWEEK_POOL, "🎁", VIOLET),
    ]:
        locked = entry["picks"].get(hw)
        remaining = sorted(pool - used)
        if locked:
            body = f"locked <b>{locked}</b>"
        elif not remaining:
            body = "<b style='color:#ef4444'>EXHAUSTED</b>"
        else:
            body = f"<b>{len(remaining)}</b>/{len(pool)} teams live"
        out.append(f"<span class='hchip' style='border-color:{color}55'>{icon} {hw}: {body}</span>")
    return " ".join(out)


def build_board(state, entry_ids, res, probs, meta, current_leg,
                loaded_legs, game_meta, records):
    """Return the full self-contained HTML document for the Board."""
    alive_n = sum(1 for e in state["entries"].values() if e["alive"])
    locked_n = sum(1 for e in entry_ids if current_leg in state["entries"][e]["picks"])

    # entry columns
    cols = []
    for e in entry_ids:
        entry = state["entries"][e]
        bkt = entry.get("bucket")
        chip, chip_color = _BUCKET_CHIP.get(bkt, _BUCKET_CHIP[None])
        alive = entry["alive"]
        locked = current_leg in entry["picks"]
        pick = entry["picks"].get(current_leg) or res.get(e, {}).get(current_leg)

        matchup = (_matchup_block(e, pick, probs, current_leg, game_meta, records, locked)
                   if pick and alive else
                   "<div class='matchup dead'>eliminated</div>" if not alive else
                   "<div class='matchup'><div class='mu-detail'>no pick clears the floor</div></div>")

        cols.append(f"""
        <div class="entry">
          <div class="e-head">
            <span class="e-dot" style="background:{'#2ecc71' if alive else '#ef4444'}"></span>
            <span class="e-name">ENTRY {e}</span>
            <span class="e-chip" style="color:{chip_color};border-color:{chip_color}44">{chip}</span>
          </div>
          {matchup}
          {_rail(entry, e, res, probs, current_leg, loaded_legs)}
          <div class="hwrap">{_holiday_chips(entry)}</div>
        </div>""")

    # decorrelation strip
    dec_rows = []
    check_legs = [lid for lid in loaded_legs
                  if lid in (set(meta.get("near_term", [])) | set(meta.get("holiday", [])))][:8]
    for lid in check_legs:
        teams = [state["entries"][e]["picks"].get(lid) or res.get(e, {}).get(lid)
                 for e in entry_ids]
        teams = [t for t in teams if t]
        if len(teams) < 2:
            continue
        ok = len(set(teams)) == len(teams)
        cls = "ok" if ok else "bad"
        label = " / ".join(teams)
        dec_rows.append(f"<span class='dchip {cls}'>{lid}: {label}</span>")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:{BG}; color:#e6e9f0; font-family:'Inter',sans-serif; padding:18px 14px 30px; }}
.hero {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; margin-bottom:6px; }}
.hero .brand {{ font-size:.72rem; font-weight:900; letter-spacing:.22em; color:{GOLD}; }}
.hero .week {{ font-size:2rem; font-weight:900; letter-spacing:-.03em; }}
.hero .pills {{ display:flex; gap:8px; margin-left:auto; }}
.pill {{ font-size:.68rem; font-weight:700; padding:4px 10px; border-radius:999px;
        border:1px solid {LINE}; color:{MUTED}; white-space:nowrap; }}
.pill.act {{ color:{GOLD}; border-color:{GOLD}66; }}
.pill.lock {{ color:{GREEN}; border-color:{GREEN}66; }}
.sub {{ color:{MUTED}; font-size:.8rem; margin-bottom:18px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:16px; }}
.entry {{ background:{CARD}; border:1px solid {LINE}; border-radius:16px; padding:16px; }}
.e-head {{ display:flex; align-items:center; gap:8px; margin-bottom:12px; }}
.e-dot {{ width:9px; height:9px; border-radius:50%; }}
.e-name {{ font-weight:900; letter-spacing:.08em; font-size:.85rem; }}
.e-chip {{ font-size:.62rem; font-weight:800; letter-spacing:.1em; padding:2px 8px;
          border-radius:999px; border:1px solid; margin-left:auto; }}
.matchup {{ background:linear-gradient(180deg, rgba(232,179,57,.06), transparent);
           border:1px solid {LINE}; border-radius:12px; padding:14px; margin-bottom:14px; }}
.matchup.dead {{ color:{MUTED}; text-align:center; padding:24px; }}
.mu-top {{ display:flex; justify-content:space-between; margin-bottom:8px; }}
.ou {{ color:{MUTED}; font-size:.7rem; font-weight:600; align-self:center; }}
.mu-team {{ font-size:1.5rem; font-weight:900; letter-spacing:-.02em; }}
.mu-team .vs {{ color:{MUTED}; font-weight:600; font-size:1rem; }}
.mu-team .ha {{ font-size:.6rem; font-weight:800; color:{MUTED}; letter-spacing:.15em;
               vertical-align:middle; margin-left:6px; }}
.rec {{ color:{MUTED}; font-size:.85rem; font-weight:600; }}
.mu-detail {{ color:{MUTED}; font-size:.78rem; margin:6px 0 10px; }}
.probwrap {{ display:flex; align-items:center; gap:10px; }}
.probbar {{ flex:1; height:8px; border-radius:999px; background:rgba(255,255,255,.07); overflow:hidden; }}
.probfill {{ height:100%; border-radius:999px; background:linear-gradient(90deg,{GOLD},#f5d47a); }}
.probnum {{ font-weight:900; font-size:1.05rem; color:{GOLD}; }}
.warn {{ margin-top:8px; color:#f59e0b; font-size:.72rem; font-weight:600; }}
.rail {{ display:flex; gap:6px; overflow-x:auto; padding:4px 2px 10px; }}
.tile {{ flex:0 0 auto; min-width:62px; text-align:center; border-radius:10px;
        padding:6px 8px; border:1.5px solid #2a3247; }}
.tile-week {{ font-size:.58rem; color:{MUTED}; font-weight:700; letter-spacing:.05em; }}
.tile-team {{ font-weight:800; font-size:.95rem; }}
.tile-sub {{ font-size:.62rem; color:{MUTED}; }}
.tile-chip {{ font-size:.5rem; font-weight:800; letter-spacing:.08em; }}
.tile.now {{ border-color:{GOLD}; background:rgba(232,179,57,.12); }}
.tile.locked {{ border-color:{GREEN}; background:rgba(46,204,113,.08); }}
.tile.hol {{ border-color:{VIOLET}; background:rgba(139,92,246,.10); }}
.tile.gap {{ border-style:dashed; opacity:.55; }}
.hwrap {{ margin-top:10px; display:flex; gap:8px; flex-wrap:wrap; }}
.hchip {{ font-size:.7rem; padding:4px 10px; border-radius:999px; border:1px solid; color:#cfd4e0; }}
.dec {{ margin-top:18px; }}
.dec h3 {{ font-size:.72rem; font-weight:800; letter-spacing:.18em; color:{MUTED}; margin-bottom:8px; }}
.dchip {{ display:inline-block; font-size:.72rem; font-weight:600; padding:4px 10px;
         border-radius:8px; margin:0 6px 6px 0; border:1px solid; }}
.dchip.ok {{ color:{GREEN}; border-color:{GREEN}44; }}
.dchip.bad {{ color:{RED}; border-color:{RED}66; background:rgba(239,68,68,.08); }}
.foot {{ margin-top:14px; color:{MUTED}; font-size:.7rem; }}
</style></head>
<body>
  <div class="hero">
    <span class="brand">CIRCA SURVIVOR 2026</span>
    <span class="week">{current_leg}</span>
    <div class="pills">
      <span class="pill">{alive_n}/{len(entry_ids)} alive</span>
      <span class="pill">{locked_n}/{alive_n} locked this week</span>
    </div>
  </div>
  <div class="sub">Live board · solver: {meta.get('status','?')} · picks re-solve weekly</div>
  <div class="grid">{''.join(cols)}</div>
  <div class="dec">
    <h3>DECORRELATION</h3>
    {''.join(dec_rows) or "<span class='dchip ok'>nothing planned yet</span>"}
  </div>
  <div class="foot">Read-only board. Lock, unlock, and what-if on the This Week and Entry tabs.</div>
</body></html>"""
