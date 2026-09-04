#!/usr/bin/env python3
"""Watch for NEW official Robinhood Stock Token pairs.

Source of truth: https://api.robinhood.com/rhj/assets (194+ registry contracts).
Name/meme ticker matching is intentionally ignored — only tokens legitimately
tied to an underlying stock/ETF in Robinhood's registry.

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
DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens/"

MIN_LIQ_USD = float(os.environ.get("RH_MIN_LIQ", "10000"))
MIN_MCAP_USD = float(os.environ.get("RH_MIN_MCAP", "20000"))
MAX_AGE_MIN = float(os.environ.get("RH_MAX_AGE_MIN", os.environ.get("RH_MAX_AGE_H", "60")))
MAX_AGE_H = MAX_AGE_MIN / 60.0
POLL_S = int(os.environ.get("RH_POLL_S", "90"))
UA = {"User-Agent": "Mozilla/5.0 PairWatch/2.0", "Accept": "application/json"}


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
    """Map lower(contractAddress) -> asset metadata from official RHJ registry."""
    body, err = get_json(RHJ_ASSETS)
    if err or not isinstance(body, dict):
        # fall back to cache
        cached = load_json(REGISTRY_CACHE, {})
        if cached.get("by_addr"):
            log(f"registry fail ({err}); using cache n={len(cached['by_addr'])}")
            return {k: v for k, v in cached["by_addr"].items()}
        log(f"registry fail: {err}")
        return {}
    by_addr: dict[str, dict] = {}
    for asset in body.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("status") or "").endswith("INACTIVE"):
            continue
        for dep in asset.get("deployments") or []:
            addr = (dep.get("contractAddress") or "").strip()
            if not addr.startswith("0x"):
                continue
            by_addr[addr.lower()] = {
                "symbol": asset.get("tokenSymbol") or "",
                "name": asset.get("tokenName") or "",
                "id": asset.get("id") or "",
                "status": asset.get("status") or "",
                "address": addr,
                "chainId": dep.get("chainId"),
                "multiplier": asset.get("currentMultiplier"),
            }
    save_json(
        REGISTRY_CACHE,
        {"ts": time.time(), "n": len(by_addr), "by_addr": by_addr},
    )
    return by_addr


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


def pair_row(p: dict, meta: dict) -> dict | None:
    base = p.get("baseToken") or {}
    addr = base.get("address") or meta.get("address") or ""
    try:
        mcap = float(p.get("marketCap") or p.get("fdv") or 0)
    except Exception:
        mcap = 0.0
    try:
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
    except Exception:
        liq = 0.0
    created = p.get("pairCreatedAt")
    age_h = None
    age_m = None
    if created:
        age_h = (time.time() * 1000 - float(created)) / 3_600_000
        age_m = age_h * 60
    ch = p.get("priceChange") or {}
    try:
        m5 = float(ch.get("m5") or 0)
    except Exception:
        m5 = 0.0

    if liq < MIN_LIQ_USD:
        return None
    if mcap < MIN_MCAP_USD:
        return None
    if age_m is not None and age_m > MAX_AGE_MIN:
        return None
    if m5 <= -25:
        return None

    return {
        "symbol": meta.get("symbol") or base.get("symbol") or "",
        "name": meta.get("name") or base.get("name") or "",
        "address": addr,
        "mcap": round(mcap),
        "liq": round(liq),
        "age_h": round(age_h, 3) if age_h is not None else None,
        "age_m": round(age_m, 1) if age_m is not None else None,
        "chg_m5": m5,
        "chg_h1": ch.get("h1"),
        "chg_h24": ch.get("h24"),
        "url": p.get("url"),
        "pair": p.get("pairAddress"),
        "official": True,
        "registry_id": meta.get("id"),
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
    """One look per official stock-token address. Never rescanned."""
    seen = set(load_json(SEEN, []))
    registry = fetch_registry()
    if not registry:
        log("no registry — abort scan")
        return []

    # Only evaluate official contracts we have never scanned
    fresh_addrs = [meta["address"] for k, meta in registry.items() if k not in seen]
    # Dex needs checksum/any case — use registry address as-is
    pairs = fetch_pairs(fresh_addrs) if fresh_addrs else []

    by_addr_pairs: dict[str, list] = {}
    for p in pairs:
        base = p.get("baseToken") or {}
        addr = (base.get("address") or "").lower()
        if not addr or addr not in registry:
            continue
        by_addr_pairs.setdefault(addr, []).append(p)

    new_hits: list[dict] = []
    # Mark every freshly considered official CA as seen (pass or fail)
    for a in fresh_addrs:
        seen.add(a.lower())

    for addr_l, plist in by_addr_pairs.items():
        meta = registry[addr_l]
        best = None
        for p in plist:
            row = pair_row(p, meta)
            if not row:
                continue
            if not best or row["liq"] > best["liq"]:
                best = row
        if best and not seed:
            new_hits.append(best)

    # Also alert brand-new registry listings with no Dex pair yet (still official)
    if not seed:
        prev_reg = set((load_json(STATE, {}).get("registry_keys") or []))
        if prev_reg:
            for k, meta in registry.items():
                if k in prev_reg:
                    continue
                if k in {h["address"].lower() for h in new_hits}:
                    continue
                # new to registry since last scan — ping even without young pair
                new_hits.append(
                    {
                        "symbol": meta.get("symbol"),
                        "name": meta.get("name"),
                        "address": meta.get("address"),
                        "mcap": None,
                        "liq": None,
                        "age_h": None,
                        "age_m": None,
                        "chg_m5": None,
                        "url": None,
                        "pair": None,
                        "official": True,
                        "registry_new": True,
                        "registry_id": meta.get("id"),
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "note": "new official stock token in RH registry",
                    }
                )

    save_json(SEEN, sorted(seen))
    save_json(
        HITS,
        {
            "ts": time.time(),
            "seed": seed,
            "hits": new_hits,
            "note": "official RH stock tokens only; one-scan; user decides",
        },
    )
    state = load_json(STATE, {})
    state.update(
        {
            "last_scan": time.time(),
            "registry_n": len(registry),
            "registry_keys": sorted(registry.keys()),
            "fresh_unseen": len(fresh_addrs),
            "new_hits": len(new_hits),
            "seen": len(seen),
            "max_age_min": MAX_AGE_MIN,
            "mode": "official_stock_tokens",
        }
    )
    save_json(STATE, state)

    if seed:
        log(f"seeded seen={len(seen)} registry={len(registry)} max_age_min={MAX_AGE_MIN}")
        return []

    if new_hits:
        log(f"NEW {len(new_hits)}: " + ", ".join(str(h.get("symbol")) for h in new_hits))
        print("\n=== RH OFFICIAL STOCK TOKEN ===")
        for h in new_hits:
            age = h.get("age_m")
            age_s = f"{age}m" if age is not None else ("registry-new" if h.get("registry_new") else "?")
            mc = h.get("mcap")
            liq = h.get("liq")
            mc_s = f"${mc:,}" if isinstance(mc, int) else "n/a"
            liq_s = f"${liq:,}" if isinstance(liq, int) else "n/a"
            print(
                f"{h.get('symbol')}  {h.get('name')}\n"
                f"  mcap={mc_s}  liq={liq_s}  age={age_s}\n"
                f"  {h.get('address')}\n"
                f"  {h.get('url') or '(no dex pair yet)'}\n"
            )
        print("===============================\n")
        print("(official stock token — one-scan only — you decide)\n")
        fire_webhook(new_hits)
    else:
        log(
            f"quiet registry={len(registry)} fresh={len(fresh_addrs)} "
            f"hits=0 seen={len(seen)} max_age_min={MAX_AGE_MIN}"
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
            f"daemon start poll={POLL_S}s min_liq={MIN_LIQ_USD} min_mcap={MIN_MCAP_USD} "
            f"max_age_min={MAX_AGE_MIN} mode=official_stock_tokens one_scan=1"
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
