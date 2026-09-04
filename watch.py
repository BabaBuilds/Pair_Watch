#!/usr/bin/env python3
"""Watch DexScreener for legitimate NEW Robinhood-chain stock-named pairs.

Pings only on first-seen hits that clear gates. No auto-buy. No FOMO %.
Usage:
  python3 scan_new_pairs.py --once
  python3 scan_new_pairs.py --daemon   # poll every POLL_S seconds
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEEN = HERE / "seen.json"
HITS = HERE / "last_hits.json"
LOG = HERE / "watch.log"
WEBHOOK = HERE / "webhook.url"
STATE = HERE / "state.json"

DEX_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_BOOSTS = "https://api.dexscreener.com/token-boosts/top/v1"
DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens/"

# Legitimate = maps to a real equity/ETF ticker (or clear stock-token branding)
STOCK_TICKERS = {
    "AAPL","MSFT","NVDA","AMZN","GOOG","GOOGL","META","TSLA","NFLX","AMD","INTC",
    "AVGO","CRM","ORCL","ADBE","CSCO","QCOM","TXN","AMAT","MU","SMCI","ARM","PLTR",
    "SNOW","NET","DDOG","CRWD","PANW","SHOP","SQ","PYPL","COIN","HOOD","MSTR","MARA",
    "RIOT","CLS","IBM","BA","CAT","GE","DIS","NKE","SBUX","COST","WMT","TGT","HD",
    "LOW","MCD","KO","PEP","JNJ","PFE","UNH","LLY","ABBV","MRK","JPM","BAC","WFC",
    "C","GS","MS","V","MA","AXP","BRK","SPY","QQQ","IWM","DIA","XLF","XLE","XLK",
    "AMC","GME","BB","NOK","BBBY","SOFI","RIVN","LCID","NIO","XPEV","LI","F","GM",
    "RBLX","U","SNAP","PINS","UBER","LYFT","ABNB","DKNG","PENN","CZR","WYNN","MGM",
    "CCL","RCL","NCLH","DAL","UAL","AAL","LUV","BA","RTX","LMT","NOC","GD","HON",
    "DE","UNP","UPS","FDX","TSM","ASML","SAP","SONY","BABA","JD","PDD","BIDU",
    "T","VZ","TMUS","CMCSA","CHTR","EA","TTWO","ATVI","SPOT","ROKU","ZM","DOCU",
    "PATH","AI","BBAI","SOUN","IONQ","RGTI","QBTS","OPEN","COMP","Z","RDFN","EXPI",
    "CVNA","KMX","AN","TSCO","ROST","TJX","DG","DLTR","KR","ACI","SFM","CELH","MNST",
    "HIMS","OSCR","CLOV","TLRY","CGC","ACB","SNDL","WEED","MSOS","BITO","IBIT","FBTC",
    "SEMI","SMH","SOXX","XBI","ARKK","ARKG","ARKW","TQQQ","SQQQ","UVXY","VIX",
}

# Extra name tokens that scream stock-token product
NAME_HINTS = re.compile(
    r"\b(stock|token|equity|share|nasdaq|nyse|jersey|treasury|folio|stocker)\b",
    re.I,
)

MIN_LIQ_USD = float(os.environ.get("RH_MIN_LIQ", "10000"))
MIN_MCAP_USD = float(os.environ.get("RH_MIN_MCAP", "20000"))
MAX_AGE_H = float(os.environ.get("RH_MAX_AGE_H", "2"))  # "new" = first 2h on Dex
POLL_S = int(os.environ.get("RH_POLL_S", "90"))
UA = {"User-Agent": "Mozilla/5.0 rh-watch/1.0", "Accept": "application/json"}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def get_json(url: str, timeout: float = 20.0):
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


def norm_sym(s: str) -> str:
    s = (s or "").upper().strip()
    s = re.sub(r"[^A-Z0-9]", "", s)
    # strip common prefixes/suffixes
    for junk in ("TOKEN", "STOCK", "COIN", "RH", "ONCHAIN"):
        if s.endswith(junk) and len(s) > len(junk) + 1:
            s = s[: -len(junk)]
    return s


def is_stock_named(symbol: str, name: str) -> bool:
    sym = norm_sym(symbol)
    if sym in STOCK_TICKERS:
        return True
    # $TICKER in name
    for m in re.findall(r"\$([A-Za-z]{1,5})\b", name or ""):
        if m.upper() in STOCK_TICKERS:
            return True
    # whole-word ticker in name
    up = (name or "").upper()
    for t in STOCK_TICKERS:
        if re.search(rf"\b{t}\b", up):
            return True
    # branded stock-token with a short ticker-like symbol
    if NAME_HINTS.search(name or "") and 1 <= len(sym) <= 5 and sym.isalpha():
        return True
    return False


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
            if not a.startswith("0x") or len(a) < 42:
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


def pair_row(p: dict) -> dict | None:
    base = p.get("baseToken") or {}
    sym = base.get("symbol") or ""
    name = base.get("name") or ""
    addr = base.get("address") or ""
    if not addr:
        return None
    if not is_stock_named(sym, name):
        return None
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
    if created:
        age_h = (time.time() * 1000 - float(created)) / 3_600_000
    ch = p.get("priceChange") or {}
    try:
        m5 = float(ch.get("m5") or 0)
    except Exception:
        m5 = 0.0

    # gates
    if liq < MIN_LIQ_USD:
        return None
    if mcap < MIN_MCAP_USD:
        return None
    if age_h is not None and age_h > MAX_AGE_H:
        return None
    # knife / one-way dump
    if m5 <= -25:
        return None

    return {
        "symbol": sym,
        "name": name,
        "address": addr,
        "mcap": round(mcap),
        "liq": round(liq),
        "age_h": round(age_h, 2) if age_h is not None else None,
        "chg_m5": m5,
        "chg_h1": ch.get("h1"),
        "chg_h24": ch.get("h24"),
        "url": p.get("url"),
        "pair": p.get("pairAddress"),
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
    payload = json.dumps({"source": "rh-watch", "n": len(hits), "hits": hits}).encode()
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
    seen = set(load_json(SEEN, []))
    addrs = collect_candidate_addrs()
    pairs = fetch_pairs(addrs)
    # best pair per token
    best: dict[str, dict] = {}
    for p in pairs:
        row = pair_row(p)
        if not row:
            continue
        k = row["address"].lower()
        prev = best.get(k)
        if not prev or row["liq"] > prev["liq"]:
            best[k] = row

    new_hits: list[dict] = []
    for k, row in best.items():
        if k in seen:
            continue
        seen.add(k)
        if seed:
            continue
        new_hits.append(row)

    save_json(SEEN, sorted(seen))
    save_json(HITS, {"ts": time.time(), "seed": seed, "hits": new_hits})
    state = load_json(STATE, {})
    state.update(
        {
            "last_scan": time.time(),
            "candidates": len(addrs),
            "stock_named_live": len(best),
            "new_hits": len(new_hits),
            "seen": len(seen),
        }
    )
    save_json(STATE, state)

    if seed:
        log(f"seeded seen={len(seen)} stock_named_live={len(best)}")
        return []

    if new_hits:
        log(f"NEW {len(new_hits)}: " + ", ".join(h["symbol"] for h in new_hits))
        print("\n=== RH NEW (stock-named) ===")
        for h in new_hits:
            print(
                f"{h['symbol']}  mcap=${h['mcap']:,}  liq=${h['liq']:,}  "
                f"age={h['age_h']}h  m5={h['chg_m5']}%\n"
                f"  {h['address']}\n  {h.get('url') or ''}\n"
            )
        print("============================\n")
        fire_webhook(new_hits)
    else:
        log(f"quiet candidates={len(addrs)} stock_named={len(best)} seen={len(seen)}")
    return new_hits


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--seed", action="store_true", help="mark current matches seen, no ping")
    args = ap.parse_args()

    if args.seed or (args.daemon and not SEEN.exists()):
        scan_once(seed=True)
        if args.seed and not args.daemon:
            return

    if args.daemon:
        log(f"daemon start poll={POLL_S}s min_liq={MIN_LIQ_USD} min_mcap={MIN_MCAP_USD} max_age_h={MAX_AGE_H}")
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
