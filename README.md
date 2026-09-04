# Pair Watch (Robinhood Chain)

Terminal watcher for **new Robinhood Chain** pairs whose ticker/name maps to a real stock or ETF.

Prints hits in your CMD/terminal. Optional webhook. No wallets, no keys, no auto-buy.

## Requirements

- Python 3.9+
- Internet
- No `pip` packages (stdlib only)

## Quick start

**Windows (CMD)**

```bat
cd Pair_Watch
run.bat
```

Or:

```bat
python watch.py --seed
python watch.py --daemon
```

**Mac / Linux**

```bash
cd Pair_Watch
chmod +x run.sh
./run.sh
```

## Commands

| Command | What it does |
|--------|----------------|
| `python watch.py --seed` | Mark current matches as seen (no spam) |
| `python watch.py --once` | One scan; print new hits as JSON |
| `python watch.py --daemon` | Keep watching (default poll 90s) |

## Filters (defaults)

- Robinhood chain only
- Stock / ETF-named tickers only
- Liquidity ≥ $10,000
- Market cap ≥ $20,000
- Pair age ≤ 2 hours
- Skip if 5m change ≤ -25%

Override with env vars:

```bat
set RH_MIN_LIQ=15000
set RH_MIN_MCAP=30000
set RH_MAX_AGE_H=1
set RH_POLL_S=60
```

## Optional webhook

Create `webhook.url` in this folder with one HTTPS URL on the first line. Each new hit POSTs JSON to that URL.

## Runtime files

Created automatically while running: `seen.json`, `last_hits.json`, `state.json`, `watch.log`.

## Disclaimer

Public market data from DexScreener. Research / education only. Not financial advice.
