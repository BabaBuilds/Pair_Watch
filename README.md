# Pair Watch (RH meme × stock-token)

Finds **new low-mcap Robinhood Chain memes** verifiably tied to an official
Robinhood Stock Token: the meme is the **base**, the stock token is the **quote**.

Example from Sep 3 night: **A Meme Coin** (`$MEME`) paired against
`AMC Entertainment • Robinhood Token` — not the multi-million AMC stock token
itself, and not random ticker cosplay.

Registry: `https://api.robinhood.com/rhj/assets`

## Quick start

**Windows:** `run.bat`  
**Mac/Linux:** `./run.sh`

```bat
python watch.py --seed
python watch.py --daemon
```

## Filters

- Quote side ∈ official RH stock-token registry; base = meme
- Pair age ≤ **60 minutes** (catch as they list)
- Meme mcap **$10k–$1M** (skip multi-millions)
- Liquidity ≥ $5k
- Skip 5m knife (≤ -25%)
- Skip stables (USDG/WETH/…) as the “meme”
- **One scan only** per meme CA — you decide after

Env: `RH_MIN_LIQ` `RH_MIN_MCAP` `RH_MAX_MCAP` `RH_MAX_AGE_MIN` `RH_POLL_S`

## Disclaimer

Research only. Not financial advice. Official stock tokens ≠ underlying equity.
