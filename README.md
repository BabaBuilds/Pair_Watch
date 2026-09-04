# Pair Watch (Robinhood Stock Tokens)

Terminal watcher for **new official Robinhood Stock Tokens** — tokens that are
legitimately tied to an underlying stock/ETF in Robinhood's public registry.

This does **not** watch meme coins that merely *look* like a ticker name.
Source of truth: `https://api.robinhood.com/rhj/assets`

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
| `python watch.py --seed` | Mark current registry tokens as seen (no spam) |
| `python watch.py --once` | One scan; print new hits as JSON |
| `python watch.py --daemon` | Keep watching (default poll 90s) |

## Filters (defaults)

- Official Robinhood Stock Token contracts only (registry)
- Liquidity ≥ $10,000 (when a Dex pair exists)
- Market cap ≥ $20,000 (when a Dex pair exists)
- Pair age ≤ 60 minutes (under 1 hour)
- Skip if 5m change ≤ -25%
- Also pings when a **new token is added to the official registry**

**One scan only:** each official token address is evaluated once. After that it is never rescanned — you trace and decide.

Override with env vars:

```bat
set RH_MIN_LIQ=15000
set RH_MIN_MCAP=30000
set RH_MAX_AGE_MIN=60
set RH_POLL_S=60
```

## Optional webhook

Create `webhook.url` in this folder with one HTTPS URL on the first line. Each new hit POSTs JSON to that URL.

## Runtime files

Created automatically while running: `seen.json`, `last_hits.json`, `state.json`, `registry.json`, `watch.log`.

## Disclaimer

Public data from Robinhood RHJ assets + DexScreener. Research / education only. Not financial advice. Stock tokens are not the underlying equity.
