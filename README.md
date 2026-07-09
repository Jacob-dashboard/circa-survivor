# Circa Survivor 2026 — Portfolio Model

Decision-support model for 2 entries in the Circa Survivor 2026 NFL contest.
MILP solver (PuLP/HiGHS) over Elo + DraftKings moneyline blend, with rolling-horizon
planning toward the Thanksgiving and Christmas Contest Weeks. See [SPEC.md](SPEC.md)
for the full design.

## Run the UI

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run survivor/ui.py
```

## CLI

```bash
python -m survivor              # status
python -m survivor forecast     # re-solve and show picks
python -m survivor lines W1     # ingest DraftKings moneylines
python -m survivor verify W1    # record survived/lost from final scores
python -m survivor check        # integrity sweep
```

## Data sources

- **Schedule / lines / scores / injuries**: ESPN public scoreboard API (unofficial,
  no auth — can change without notice)
- **Betting splits**: VSiN DraftKings splits page (scrape; populates in-season)
- **Win totals**: DraftKings via RotoWire, June 2026 snapshot, all 32 verified

## State

`survivor/season_state.json` is the living season state — picks, buckets, Elo
nudges, line overrides. The UI and CLI both read/write it. In-season nudges go
through `state.adjust_strength()`, never by editing `data.py`.
