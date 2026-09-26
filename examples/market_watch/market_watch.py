#!/usr/bin/env python3
"""Watch the New York, Sydney and Tokyo stock markets from any time zone.

Pulls index quotes from Yahoo Finance's public chart endpoint using only the
Python standard library, shows whether each exchange is open, and converts
session hours to your local time zone (Jamaica by default).

Examples
--------
    python market_watch.py                      # one snapshot
    python market_watch.py --watch 60           # refresh every 60 seconds
    python market_watch.py --alert 1.0          # flag moves of +/-1% or more
    python market_watch.py --market ny tokyo    # only some markets
    python market_watch.py --json               # machine-readable output
    python market_watch.py --tz America/Toronto # another local time zone
    python market_watch.py --out snapshot/      # one JSON file per market
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import (
    date,
    datetime,
    time as dtime,
    timedelta,
    timezone,
)
from pathlib import Path
from zoneinfo import ZoneInfo

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (market_watch.py)"

# Regular trading hours in each exchange's own time zone. Exchange holidays
# are not modelled; the quote timestamp shows when an index last traded.
MARKETS: dict[str, dict] = {
    "ny": {
        "name": "New York",
        "exchange": "NYSE / Nasdaq",
        "tz": "America/New_York",
        "open": dtime(9, 30),
        "close": dtime(16, 0),
        "indices": [
            ("^GSPC", "S&P 500"),
            ("^DJI", "Dow Jones"),
            ("^IXIC", "Nasdaq Composite"),
            ("^NDX", "Nasdaq-100"),
        ],
    },
    "sydney": {
        "name": "Sydney",
        "exchange": "ASX",
        "tz": "Australia/Sydney",
        "open": dtime(10, 0),
        "close": dtime(16, 0),
        "indices": [
            ("^AXJO", "S&P/ASX 200"),
            ("^AORD", "All Ordinaries"),
        ],
    },
    "tokyo": {
        "name": "Tokyo",
        "exchange": "Tokyo Stock Exchange",
        "tz": "Asia/Tokyo",
        "open": dtime(9, 0),
        "close": dtime(15, 30),
        "indices": [
            ("^N225", "Nikkei 225"),
        ],
    },
}


def fetch_chart(symbol: str, retries: int = 2) -> dict:
    """Return the chart result for one symbol (today's session, 5-minute bars)."""
    query = urllib.parse.urlencode({"range": "1d", "interval": "5m"})
    url = CHART_URL.format(symbol=urllib.parse.quote(symbol)) + "?" + query
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                payload = json.load(response)
            chart = payload["chart"]
            if chart.get("error"):
                raise RuntimeError(chart["error"].get("description", "unknown error"))
            return chart["result"][0]
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def quote(symbol: str, name: str) -> dict:
    """Latest price, change against the previous close, and an intraday series."""
    result = fetch_chart(symbol)
    meta = result["meta"]
    price = meta["regularMarketPrice"]
    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
    change = price - prev_close if prev_close else None
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "change": change,
        "pct": 100 * change / prev_close if prev_close else None,
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "as_of": datetime.fromtimestamp(meta["regularMarketTime"], timezone.utc).isoformat(),
        "spark": [round(c, 2) for c in closes if c is not None],
    }


def session(market: dict, now: datetime, local_tz: ZoneInfo) -> dict:
    """Open/closed state and the next open or close, in exchange and local time."""
    tz = ZoneInfo(market["tz"])
    here = now.astimezone(tz)

    def at(day: date, t: dtime) -> datetime:
        return datetime.combine(day, t, tzinfo=tz)

    is_open = here.weekday() < 5 and at(here.date(), market["open"]) <= here < at(here.date(), market["close"])
    if is_open:
        next_event, label = at(here.date(), market["close"]), "closes"
    else:
        day = here.date()
        if here >= at(day, market["open"]):
            day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        next_event, label = at(day, market["open"]), "opens"

    today = here.date()
    return {
        "is_open": is_open,
        "exchange_time": here.isoformat(),
        "next_event": label,
        "next_event_at": next_event.astimezone(timezone.utc).isoformat(),
        "next_event_local": next_event.astimezone(local_tz).strftime("%a %H:%M"),
        "hours_local": "{}-{}".format(
            at(today, market["open"]).astimezone(local_tz).strftime("%H:%M"),
            at(today, market["close"]).astimezone(local_tz).strftime("%H:%M"),
        ),
    }


def snapshot(keys: list[str], local_tz: ZoneInfo) -> dict:
    """Quotes and session state for the chosen markets."""
    now = datetime.now(timezone.utc)
    markets = {}
    for key in keys:
        market = MARKETS[key]
        indices = []
        for symbol, name in market["indices"]:
            try:
                indices.append(quote(symbol, name))
            except Exception as exc:  # keep the other markets if one symbol fails
                indices.append({"symbol": symbol, "name": name, "error": str(exc)})
        markets[key] = {
            "name": market["name"],
            "exchange": market["exchange"],
            "tz": market["tz"],
            **session(market, now, local_tz),
            "indices": indices,
        }
    return {"updated_at": now.isoformat(), "local_tz": str(local_tz), "markets": markets}


def render(data: dict, alert: float | None) -> str:
    """Format a snapshot as a plain-text table."""
    local_tz = ZoneInfo(data["local_tz"])
    updated = datetime.fromisoformat(data["updated_at"]).astimezone(local_tz)
    lines = [f"Market watch - {updated:%a %d %b %Y %H:%M} ({data['local_tz']})", ""]
    alerts = []
    for market in data["markets"].values():
        state = "OPEN" if market["is_open"] else "CLOSED"
        lines.append(
            f"{market['name']} ({market['exchange']}) - {state}, "
            f"{market['next_event']} {market['next_event_local']} your time "
            f"[hours {market['hours_local']} your time]"
        )
        for q in market["indices"]:
            if "error" in q:
                lines.append(f"  {q['name']:<18} unavailable: {q['error']}")
                continue
            as_of = datetime.fromisoformat(q["as_of"]).astimezone(local_tz)
            pct = f"{q['pct']:+.2f}%" if q["pct"] is not None else "n/a"
            chg = f"{q['change']:+,.2f}" if q["change"] is not None else ""
            lines.append(f"  {q['name']:<18} {q['price']:>12,.2f}  {chg:>10}  {pct:>7}   as of {as_of:%a %H:%M}")
            if alert is not None and q["pct"] is not None and abs(q["pct"]) >= alert:
                alerts.append(f"{q['name']} {pct}")
        lines.append("")
    if alerts:
        lines.append(f"ALERT (moves of {alert:g}% or more): " + ", ".join(alerts))
    return "\n".join(lines).rstrip()


def write_files(data: dict, out_dir: str) -> None:
    """Write one self-contained JSON document per market."""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for key, market in data["markets"].items():
        doc = {"key": key, "updated_at": data["updated_at"], **market}
        (folder / f"{key}.json").write_text(json.dumps(doc, indent=2))


def main() -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--market",
        nargs="+",
        choices=list(MARKETS),
        default=list(MARKETS),
        help="markets to show (default: all)",
    )
    parser.add_argument(
        "--tz",
        default="America/Jamaica",
        help="your IANA time zone (default: America/Jamaica)",
    )
    parser.add_argument("--watch", type=int, metavar="SECONDS", help="refresh every N seconds")
    parser.add_argument("--alert", type=float, metavar="PCT", help="flag daily moves of at least PCT%%")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument(
        "--out",
        metavar="DIR",
        help="also write <market>.json per market into DIR (for the dashboard)",
    )
    args = parser.parse_args()

    local_tz = ZoneInfo(args.tz)
    while True:
        data = snapshot(args.market, local_tz)
        if args.out:
            write_files(data, args.out)
        if args.json:
            print(json.dumps(data, indent=2))  # noqa: T201
        else:
            if args.watch:
                print("\033[2J\033[H", end="")  # noqa: T201  clears the terminal
            print(render(data, args.alert))  # noqa: T201
        if not args.watch:
            return 0
        time.sleep(max(args.watch, 15))


if __name__ == "__main__":
    sys.exit(main())
