#!/usr/bin/env python3
"""Watch NEW low-mcap Robinhood memes that are verifiably tied to official RH stock tokens.

A pair counts when one side is an official Robinhood Stock Token
(from https://api.robinhood.com/rhj/assets) and the other side is a meme.
Example: "A Meme Coin" paired with AMC Entertainment • Robinhood Token.

We alert on the MEME side as it lists — not the multi-million official stock tokens.

Usage:
  python watch.py --seed
  python watch.py --once
  python watch.py --daemon
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEEN = HERE / "seen.json"
HITS = HERE / "last_hits.json"
LOG = HERE / "watch.log"
WEBHOOK = HERE / "webhook.url"
STATE = HERE / "state.json"
REGISTRY_CACHE = HERE / "registry.json"

RHJ_ASSETS = "https://api.robinhood.com/rhj/assets"
DEX_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_BOOSTS = "https://api.dexscreener.com/token-boosts/top/v1"
DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens/"

MIN_LIQ_USD = float(os.environ.get("RH_MIN_LIQ", "5000"))
MIN_MCAP_USD = float(os.environ.get("RH_MIN_MCAP", "10000"))
MAX_MCAP_USD = float(os.environ.get("RH_MAX_MCAP", "1000000"))  # skip multi-millions
MAX_AGE_MIN = float(os.environ.get("RH_MAX_AGE_MIN", "60"))
POLL_S = int(os.environ.get("RH_POLL_S", "90"))
UA = {"User-Agent": "Mozilla/5.0 PairWatch/3.0", "Accept": "application/json"}

# Never treat these as the "meme" side of a stock-token pair
STABLE_OR_GAS = {
    "usdg", "usdc", "usdt", "dai", "usd1", "weth", "eth", "wbnb", "bnb",
    "wsol", "sol", "rhusd", "cash",
}
STABLE_ADDR = {
    # Global Dollar / common RH quotes if known
    "0x5fc5360d0400a0fd4f2af552add042d716f1d168",  # USDG on RH
    "0x0bd7d308f8e1639fab988df18a8011f41eacad73",  # WETH on RH
    "0x0000000000000000000000000000000000000000",
}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def get_json(url: str, timeout: float = 25.0):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), None
    except Exception as e:
        return None, str(e)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2))


def fetch_registry() -> dict[str, dict]:
    body, err = get_json(RHJ_ASSETS)
    if err or not isinstance(body, dict):
        cached = load_json(REGISTRY_CACHE, {})
        if cached.get("by_addr"):
            log(f"registry fail ({err}); using cache n={len(cached['by_addr'])}")
            return dict(cached["by_addr"])
        log(f"registry fail: {err}")
        return {}
    by_addr: dict[str, dict] = {}
    for asset in body.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if "INACTIVE" in str(asset.get("status") or ""):
            continue
        for dep in asset.get("deployments") or []:
            addr = (dep.get("contractAddress") or "").strip()
            if not addr.startswith("0x"):
                continue
            by_addr[addr.lower()] = {
                "symbol": asset.get("tokenSymbol") or "",
                "name": asset.get("tokenName") or "",
                "id": asset.get("id") or "",
                "address": addr,
            }
    save_json(REGISTRY_CACHE, {"ts": time.time(), "n": len(by_addr), "by_addr": by_addr})
    return by_addr


def collect_candidate_addrs() -> list[str]:
    addrs: list[str] = []
    seen: set[str] = set()
    for url in (DEX_PROFILES, DEX_BOOSTS):
        body, err = get_json(url)
        if err or not isinstance(body, list):
            log(f"list fail {url}: {err}")
            continue
        for row in body:
            if not isinstance(row, dict):
                continue
            if str(row.get("chainId") or "").lower() != "robinhood":
                continue
            a = (row.get("tokenAddress") or row.get("address") or "").strip()
            if not a.startswith("0x"):
                continue
            k = a.lower()
            if k in seen:
                continue
            seen.add(k)
            addrs.append(a)
    return addrs


def fetch_pairs(addrs: list[str]) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(addrs), 30):
        batch = addrs[i : i + 30]
        body, err = get_json(DEX_TOKENS + ",".join(batch))
        if err or not isinstance(body, dict):
            log(f"tokens fail: {err}")
            continue
        for p in body.get("pairs") or []:
            if str(p.get("chainId") or "").lower() != "robinhood":
                continue
            out.append(p)
        time.sleep(0.25)
    return out


def meme_mcap_from_pairs(meme_addr: str, pairs: list[dict]) -> float:
    """Best marketCap from pairs where meme is baseToken (Dex mcap is base-sided)."""
    best = 0.0
    best_liq = -1.0
    k = meme_addr.lower()
    for p in pairs:
        if str(p.get("chainId") or "").lower() != "robinhood":
            continue
        base = p.get("baseToken") or {}
        if (base.get("address") or "").lower() != k:
            continue
        try:
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
        except Exception:
            liq = 0.0
        try:
            mcap = float(p.get("marketCap") or p.get("fdv") or 0)
        except Exception:
            mcap = 0.0
        if liq >= best_liq and mcap > 0:
            best_liq = liq
            best = mcap
    return best


def evaluate_pair(p: dict, registry: dict[str, dict], mcap_hint: float | None = None) -> dict | None:
    """Hit when meme is paired with an official RH stock token (either orientation).

    Last night's $MEME (0x385f4f8…) was AMC(official)/MEME — stock as base, meme as quote.
    Smaller clones were often MEME/AMC — meme as base. Catch both.
    """
    base = p.get("baseToken") or {}
    quote = p.get("quoteToken") or {}
    ba = (base.get("address") or "").lower()
    qa = (quote.get("address") or "").lower()
    if not ba or not qa:
        return None

    base_off = ba in registry
    quote_off = qa in registry
    if base_off == quote_off:
        return None  # both official or neither

    if quote_off and not base_off:
        # meme / STOCK  (meme is base — pair mcap is meme's)
        meme, stock_meta = base, registry[qa]
        meme_addr = ba
        mcap_from_pair = True
    else:
        # STOCK / meme  (last-night $MEME style — pair mcap is the stock's, ignore it)
        meme, stock_meta = quote, registry[ba]
        meme_addr = qa
        mcap_from_pair = False

    if meme_addr in registry:
        return None
    sym = (meme.get("symbol") or "").strip().lower()
    if sym in STABLE_OR_GAS or meme_addr in STABLE_ADDR:
        return None

    try:
        pair_mcap = float(p.get("marketCap") or p.get("fdv") or 0)
    except Exception:
        pair_mcap = 0.0
    if mcap_from_pair:
        mcap = pair_mcap
    elif mcap_hint is not None and mcap_hint > 0:
        mcap = mcap_hint
    else:
        # defer — caller must re-eval with hint
        mcap = -1.0

    try:
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
    except Exception:
        liq = 0.0
    created = p.get("pairCreatedAt")
    age_m = None
    if created:
        age_m = (time.time() * 1000 - float(created)) / 60_000
    ch = p.get("priceChange") or {}
    try:
        m5 = float(ch.get("m5") or 0)
    except Exception:
        m5 = 0.0

    if liq < MIN_LIQ_USD:
        return None
    if age_m is not None and age_m > MAX_AGE_MIN:
        return None
    if m5 <= -25:
        return None
    if mcap < 0:
        return {
            "_needs_mcap": True,
            "symbol": meme.get("symbol") or "",
            "name": meme.get("name") or "",
            "address": meme.get("address") or "",
            "mcap": None,
            "liq": round(liq),
            "age_m": round(age_m, 1) if age_m is not None else None,
            "chg_m5": m5,
            "chg_h1": ch.get("h1"),
            "chg_h24": ch.get("h24"),
            "url": p.get("url"),
            "pair": p.get("pairAddress"),
            "tied_stock": stock_meta.get("symbol"),
            "tied_stock_name": stock_meta.get("name"),
            "tied_stock_address": stock_meta.get("address"),
            "orientation": "stock_base_meme_quote",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    if mcap < MIN_MCAP_USD or mcap > MAX_MCAP_USD:
        return None

    return {
        "symbol": meme.get("symbol") or "",
        "name": meme.get("name") or "",
        "address": meme.get("address") or "",
        "mcap": round(mcap),
        "liq": round(liq),
        "age_m": round(age_m, 1) if age_m is not None else None,
        "chg_m5": m5,
        "chg_h1": ch.get("h1"),
        "chg_h24": ch.get("h24"),
        "url": p.get("url"),
        "pair": p.get("pairAddress"),
        "tied_stock": stock_meta.get("symbol"),
        "tied_stock_name": stock_meta.get("name"),
        "tied_stock_address": stock_meta.get("address"),
        "orientation": "meme_base_stock_quote" if mcap_from_pair else "stock_base_meme_quote",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def fire_webhook(hits: list[dict]) -> None:
    if not hits:
        return
    url = ""
    if WEBHOOK.exists():
        url = WEBHOOK.read_text().strip().splitlines()[0].strip()
    if not url:
        log("no webhook.url — hits saved only")
        return
    payload = json.dumps({"source": "pair-watch", "n": len(hits), "hits": hits}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": UA["User-Agent"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            log(f"webhook {r.status} n={len(hits)}")
    except Exception as e:
        log(f"webhook fail: {e}")


def scan_once(seed: bool = False) -> list[dict]:
    """One look per meme CA. Once scanned, never again — user decides."""
    seen = set(load_json(SEEN, []))
    registry = fetch_registry()
    if not registry:
        log("no registry — abort")
        return []

    addrs = collect_candidate_addrs()
    # also probe a rotating slice of official stock tokens for brand-new meme pairs
    # (cheap: only tokens not recently checked via profiles)
    regs = list(registry.values())
    # rotate through full registry so every stock token gets probed over time
    start = int(time.time() // POLL_S) % max(len(regs), 1)
    official_sample = (regs + regs)[start : start + 50]
    probe = [m["address"] for m in official_sample]
    all_addrs = []
    seen_batch = set()
    for a in addrs + probe:
        k = a.lower()
        if k in seen_batch:
            continue
        seen_batch.add(k)
        all_addrs.append(a)

    fresh_meme_candidates = [a for a in addrs if a.lower() not in seen and a.lower() not in registry]
    pairs = fetch_pairs(all_addrs)

    best: dict[str, dict] = {}
    need_mcap: dict[str, dict] = {}
    for p in pairs:
        row = evaluate_pair(p, registry)
        if not row:
            continue
        k = row["address"].lower()
        if k in seen:
            continue
        if row.pop("_needs_mcap", False):
            prev = need_mcap.get(k)
            if not prev or row["liq"] > prev["liq"]:
                need_mcap[k] = row
            continue
        prev = best.get(k)
        if not prev or row["liq"] > prev["liq"]:
            best[k] = row

    # Resolve meme mcap when stock was base (Dex pair mcap = stock, not meme)
    if need_mcap:
        meme_pairs = fetch_pairs([row["address"] for row in need_mcap.values()])
        for k, row in need_mcap.items():
            hint = meme_mcap_from_pairs(k, meme_pairs)
            if hint < MIN_MCAP_USD or hint > MAX_MCAP_USD:
                continue
            row["mcap"] = round(hint)
            prev = best.get(k)
            if not prev or row["liq"] > prev["liq"]:
                best[k] = row

    # Mark every newly considered meme candidate as seen (one-scan), pass or fail
    for a in fresh_meme_candidates:
        seen.add(a.lower())
    # Also mark hit memes found via official-token probe
    for k in best:
        seen.add(k)

    new_hits: list[dict] = []
    if not seed:
        new_hits = list(best.values())

    save_json(SEEN, sorted(seen))
    save_json(
        HITS,
        {
            "ts": time.time(),
            "seed": seed,
            "hits": new_hits,
            "note": "meme paired with official RH stock token; one-scan; user decides",
        },
    )
    state = load_json(STATE, {})
    state.update(
        {
            "last_scan": time.time(),
            "registry_n": len(registry),
            "candidates": len(addrs),
            "fresh_unseen": len(fresh_meme_candidates),
            "new_hits": len(new_hits),
            "seen": len(seen),
            "max_age_min": MAX_AGE_MIN,
            "max_mcap": MAX_MCAP_USD,
            "mode": "meme_tied_to_official_stock_token",
        }
    )
    save_json(STATE, state)

    if seed:
        # on seed, mark all currently-tied memes seen too so we don't spam old MEME/AMC
        for p in pairs:
            row = evaluate_pair(p, registry)
            if row:
                seen.add(row["address"].lower())
        for a in addrs:
            if a.lower() not in registry:
                seen.add(a.lower())
        save_json(SEEN, sorted(seen))
        state["seen"] = len(seen)
        save_json(STATE, state)
        log(f"seeded seen={len(seen)} registry={len(registry)} max_age_min={MAX_AGE_MIN} max_mcap={MAX_MCAP_USD}")
        return []

    if new_hits:
        log(f"NEW {len(new_hits)}: " + ", ".join(f"{h['symbol']}/{h['tied_stock']}" for h in new_hits))
        print("\n=== RH MEME x STOCK-TOKEN ===")
        for h in new_hits:
            print(
                f"{h['symbol']}  ({h['name']})\n"
                f"  tied to ${h['tied_stock']}  {h['tied_stock_name']}\n"
                f"  mcap=${h['mcap']:,}  liq=${h['liq']:,}  age={h['age_m']}m\n"
                f"  {h['address']}\n"
                f"  {h.get('url') or ''}\n"
            )
        print("=============================\n")
        print("(one-scan only — you decide from here)\n")
        fire_webhook(new_hits)
    else:
        log(
            f"quiet candidates={len(addrs)} fresh={len(fresh_meme_candidates)} "
            f"hits=0 seen={len(seen)} max_age_min={MAX_AGE_MIN} max_mcap={MAX_MCAP_USD}"
        )
    return new_hits


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--seed", action="store_true")
    args = ap.parse_args()

    if args.seed or (args.daemon and not SEEN.exists()):
        scan_once(seed=True)
        if args.seed and not args.daemon:
            return

    if args.daemon:
        log(
            f"daemon start poll={POLL_S}s liq>={MIN_LIQ_USD} mcap={MIN_MCAP_USD}-{MAX_MCAP_USD} "
            f"max_age_min={MAX_AGE_MIN} mode=meme_x_stock_token one_scan=1"
        )
        while True:
            try:
                scan_once(seed=False)
            except Exception as e:
                log(f"scan error: {e}")
            time.sleep(POLL_S)
    else:
        hits = scan_once(seed=False)
        print(json.dumps(hits, indent=2))


if __name__ == "__main__":
    main()
