# Market watch: New York, Sydney and Tokyo

`market_watch.py` shows the main stock indices for three exchanges, whether each
one is open, and its trading hours in your own time zone (Jamaica by default).
It uses only the Python standard library (3.9+) and Yahoo Finance's public chart
data, so there is nothing to install and no API key.

| Market | Exchange | Indices |
|---|---|---|
| New York | NYSE / Nasdaq | S&P 500, Dow Jones, Nasdaq Composite, Nasdaq-100 |
| Sydney | ASX | S&P/ASX 200, All Ordinaries |
| Tokyo | Tokyo Stock Exchange | Nikkei 225 |

## Usage

```sh
python market_watch.py                      # one snapshot
python market_watch.py --watch 60           # refresh every 60 seconds
python market_watch.py --alert 1.0          # flag daily moves of +/-1% or more
python market_watch.py --market ny tokyo    # only some markets
python market_watch.py --json               # JSON output
python market_watch.py --out snapshot/      # also write one JSON file per market
python market_watch.py --tz America/Toronto # a different local time zone
```

## Trading hours in Jamaica time

Jamaica stays on UTC-5 all year, but New York and Sydney change their clocks, so
the hours shift during the year. The script works these out for the current date.

| Market | Local hours | Jamaica time, US summer time (Mar-Nov) | Jamaica time, US winter |
|---|---|---|---|
| New York | 09:30-16:00 | 08:30-15:00 | 09:30-16:00 |
| Tokyo | 09:00-15:30 | 19:00-01:30 (evening before) | 19:00-01:30 |
| Sydney | 10:00-16:00 | 18:00-00:00 (Oct-Apr), 19:00-01:00 (Apr-Oct) | same |

Exchange holidays are not modelled. Each quote's "as of" time shows when the
index last traded.
