# Pair Watch (RH meme × stock-token)

Finds **new low-mcap Robinhood Chain memes** verifiably tied to an official
Robinhood Stock Token — either orientation:

- meme / STOCK (meme base, stock quote)
- STOCK / meme (stock base, meme quote) — e.g. last night’s
  **A Meme Coin** `0x385f4f8ae47651ce5f58f5265395a669f8281e18` vs AMC

Not the multi-million official stock tokens themselves. Not ticker cosplay.

Registry: `https://api.robinhood.com/rhj/assets`

## Quick start

**Windows:** `run.bat`  
**Mac/Linux:** `./run.sh`

```bat
python watch.py --seed
python watch.py --daemon
```

## Filters

- One side ∈ official RH stock-token registry; other side = meme
- Pair age ≤ **60 minutes**
- Meme mcap **$10k–$1M** (resolved on the meme leg, not the stock’s mcap)
- Liquidity ≥ $5k
- Skip 5m knife (≤ -25%) and stables as the “meme”
- **One scan only** per meme CA

Env: `RH_MIN_LIQ` `RH_MIN_MCAP` `RH_MAX_MCAP` `RH_MAX_AGE_MIN` `RH_POLL_S`

## Disclaimer

Research only. Not financial advice. Official stock tokens ≠ underlying equity.
