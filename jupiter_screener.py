#!/usr/bin/env python3

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search?q=solana"

# Additional queries to broaden Solana coverage. DexScreener search is fuzzy and
# returns a small subset per query, so we combine multiple.
DEFAULT_EXTRA_QUERIES = [
    "quote:USDC solana",
    "chain:solana USDC",
    "SOL USDC",
    "SOLANA USDC",
    "chain:solana",
]


def fetch_solana_pairs(
    timeout_secs: float = 15.0,
    extra_queries: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    queries = [DEXSCREENER_SEARCH]
    for q in (extra_queries or DEFAULT_EXTRA_QUERIES):
        queries.append(
            "https://api.dexscreener.com/latest/dex/search?q="
            + urllib.parse.quote(q)
        )

    combined: List[Dict[str, Any]] = []
    seen_pairs: set[str] = set()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

    for url in queries:
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout_secs) as resp:
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            pairs = data.get("pairs", [])
        except Exception:
            pairs = []

        for p in pairs:
            if p.get("chainId") != "solana":
                continue
            pair_addr = p.get("pairAddress") or p.get("url")
            if not pair_addr or pair_addr in seen_pairs:
                continue
            seen_pairs.add(pair_addr)
            combined.append(p)

    return combined


def coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def abbreviate_number(value: float) -> str:
    abs_v = abs(value)
    if abs_v >= 1_000_000_000:
        return f"{value/1_000_000_000:.2f}B"
    if abs_v >= 1_000_000:
        return f"{value/1_000_000:.2f}M"
    if abs_v >= 1_000:
        return f"{value/1_000:.2f}k"
    return f"{value:.2f}"


def format_price(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if value >= 1:
        return f"{value:,.2f}"
    if value >= 0.01:
        return f"{value:,.4f}"
    return f"{value:.8f}"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def screen_pairs(
    pairs: List[Dict[str, Any]],
    quote_filter: Optional[str],
    min_liquidity_usd: float,
    min_volume_m5_usd: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    filtered: List[Dict[str, Any]] = []
    for p in pairs:
        quote_symbol = (
            (p.get("quoteToken") or {}).get("symbol") or ""
        ).upper()
        if quote_filter and quote_symbol != quote_filter.upper():
            continue

        liquidity_usd = coerce_float((p.get("liquidity") or {}).get("usd"))
        if liquidity_usd is None or liquidity_usd < min_liquidity_usd:
            continue

        vol_m5 = coerce_float((p.get("volume") or {}).get("m5"))
        if vol_m5 is None or vol_m5 < min_volume_m5_usd:
            continue

        change_m5 = coerce_float((p.get("priceChange") or {}).get("m5"))
        price_usd = coerce_float(p.get("priceUsd"))

        # Skip if we don't have change info
        if change_m5 is None:
            continue

        record = {
            "symbol": (p.get("baseToken") or {}).get("symbol") or "?",
            "base_address": (p.get("baseToken") or {}).get("address"),
            "quote": quote_symbol,
            "dex": p.get("dexId") or "?",
            "pair": p.get("pairAddress") or "?",
            "url": p.get("url"),
            "price_usd": price_usd,
            "change_m5": change_m5,
            "vol_m5": vol_m5,
            "liquidity_usd": liquidity_usd,
        }
        filtered.append(record)

    gainers = sorted(filtered, key=lambda x: (x["change_m5"]) , reverse=True)
    losers = sorted(filtered, key=lambda x: (x["change_m5"]))
    return gainers, losers


def print_tables(
    gainers: List[Dict[str, Any]],
    losers: List[Dict[str, Any]],
    limit: int,
    title_suffix: str,
):
    # Clear screen
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()

    print(f"Solana 5m Movers {title_suffix} — {now_utc_iso()}")
    print("=")

    def print_table(title: str, items: List[Dict[str, Any]]):
        print(title)
        print(
            f"{'#':>2}  {'Symbol':<12} {'Quote':<5} {'DEX':<10} "
            f"{'Price($)':>12} {'Δ5m%':>8} {'Vol5m($)':>12} {'Liq($)':>12}"
        )
        print("-" * 78)
        for idx, r in enumerate(items[:limit], start=1):
            price_str = format_price(r.get("price_usd"))
            change_str = f"{r['change_m5']:>+7.2f}"
            vol_str = f"{abbreviate_number(r['vol_m5']):>12}"
            liq_str = f"{abbreviate_number(r['liquidity_usd']):>12}"
            print(
                f"{idx:>2}  {r['symbol']:<12} {r['quote']:<5} {r['dex']:<10} "
                f"{price_str:>12} {change_str:>8} {vol_str} {liq_str}"
            )
        print()

    print_table("Top Gainers (5m)", gainers)
    print_table("Top Losers (5m)", losers)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Real-time Solana spot screener using DexScreener — "
            "shows top 5-minute gainers/losers with volume/liquidity filters."
        )
    )
    parser.add_argument("--refresh", type=float, default=10.0, help="Refresh interval in seconds")
    parser.add_argument("--limit", type=int, default=10, help="Rows per table")
    parser.add_argument(
        "--quote",
        type=str,
        default="USDC",
        help="Filter by quote symbol (e.g., USDC, SOL). Empty = all",
    )
    parser.add_argument(
        "--min-liquidity",
        type=float,
        default=50_000.0,
        help="Minimum liquidity USD",
    )
    parser.add_argument(
        "--min-volume-m5",
        type=float,
        default=10_000.0,
        help="Minimum 5-minute volume USD",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="Number of refresh iterations to run (0 for infinite)",
    )
    parser.add_argument(
        "--extra-query",
        action="append",
        default=None,
        help=(
            "Extra DexScreener search query. Can be provided multiple times. "
            "Example: --extra-query 'quote:USDC chain:solana'"
        ),
    )

    args = parser.parse_args()

    # Normalize quote filter: empty string or 'ANY' disables filtering
    quote_filter: Optional[str]
    if not args.quote or args.quote.strip().upper() in {"ANY", "ALL", "*"}:
        quote_filter = None
    else:
        quote_filter = args.quote.strip().upper()

    iteration = 0
    while True:
        iteration += 1
        try:
            pairs = fetch_solana_pairs(extra_queries=args.extra_query)
            gainers, losers = screen_pairs(
                pairs,
                quote_filter=quote_filter,
                min_liquidity_usd=args.min_liquidity,
                min_volume_m5_usd=args.min_volume_m5,
            )
            title_suffix = (
                f"[quote={quote_filter or 'ANY'}, liq>={int(args.min_liquidity)}, "
                f"vol5m>={int(args.min_volume_m5)}]"
            )
            print_tables(gainers, losers, args.limit, title_suffix)
        except urllib.error.HTTPError as e:
            print(f"HTTP error: {e}")
        except urllib.error.URLError as e:
            print(f"Network error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

        if args.iterations and iteration >= args.iterations:
            break
        time.sleep(max(args.refresh, 0.1))


if __name__ == "__main__":
    main()
