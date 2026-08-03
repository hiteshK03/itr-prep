"""Daily USD closing prices, needed to value holdings on every day of the year.

Source is Yahoo Finance's public chart endpoint, called with plain `requests`. Two
alternatives were tried and rejected:

  - Stooq's CSV download now sits behind a JavaScript proof-of-work anti-bot wall and
    returns an HTML challenge page instead of data.
  - yfinance 1.5.2 routes through curl_cffi, whose bundled CA bundle would not verify;
    every call failed with CertificateVerifyError before it reached Yahoo.

Everything is cached to disk per ticker per year, and a manual override CSV can supply or
correct any (ticker, date) close so a network failure or a delisted/renamed symbol never
blocks a filing.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
from decimal import Decimal

import requests

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

# Yahoo rejects requests without a browser-ish User-Agent.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


class PriceError(Exception):
    pass


class PriceSeries:
    """Trading-day closes for one ticker, with as-of lookup.

    `splits` carries the corporate actions Yahoo reports for the ticker, as
    (effective date, ratio) where a 10-for-1 split has ratio 10. These matter because
    Yahoo's closes are **retroactively split-adjusted** while a broker statement is not,
    so a holding spanning a split will silently mis-value by the split factor unless the
    quantities are restated. See positions.check_splits.
    """

    def __init__(self, ticker: str, closes: dict[dt.date, Decimal],
                 splits: list[tuple[dt.date, Decimal]] | None = None):
        self.ticker = ticker
        self._closes = closes
        self._sorted = sorted(closes)
        self.splits = sorted(splits or [])

    def __len__(self) -> int:
        return len(self._closes)

    @property
    def trading_days(self) -> list[dt.date]:
        return list(self._sorted)

    def close_on(self, day: dt.date) -> tuple[Decimal, dt.date]:
        """Close for `day`, or the most recent earlier trading day.

        Markets are shut at weekends and on US holidays. A holding still exists on those
        days, so it is valued at its last traded price, which is also how a broker
        statement would show it.
        """
        if day in self._closes:
            return self._closes[day], day
        earlier = [d for d in self._sorted if d <= day]
        if not earlier:
            raise PriceError(
                f"{self.ticker}: no close on or before {day} "
                f"(series starts {self._sorted[0] if self._sorted else 'n/a'})"
            )
        chosen = earlier[-1]
        return self._closes[chosen], chosen


class PriceStore:
    """Cache-first price fetcher with a manual override layer on top."""

    def __init__(self, cache_dir: str, overrides_path: str | None = None,
                 offline: bool = False):
        self.cache_dir = cache_dir
        self.offline = offline
        os.makedirs(cache_dir, exist_ok=True)
        self._overrides = _load_overrides(overrides_path) if overrides_path else {}
        self._series: dict[tuple[str, int], PriceSeries] = {}

    def series(self, ticker: str, year: int) -> PriceSeries:
        key = (ticker.upper(), year)
        if key in self._series:
            return self._series[key]

        cached = self._from_cache(ticker, year)
        if cached is None:
            if self.offline:
                closes, splits = {}, []
            else:
                try:
                    closes, splits = self._fetch(ticker, year)
                    self._to_cache(ticker, year, closes, splits)
                except Exception as exc:  # network, rate limit, unknown symbol
                    closes, splits = {}, []
                    self._fetch_error = f"{ticker} {year}: {exc}"
        else:
            closes, splits = cached

        # Overrides win over anything fetched, and can stand alone if the fetch failed.
        for (ov_ticker, ov_date), price in self._overrides.items():
            if ov_ticker == ticker.upper() and ov_date.year == year:
                closes[ov_date] = price

        if not closes:
            raise PriceError(
                f"No daily prices available for {ticker} in {year}.\n"
                f"Either re-run with network access, or add rows to your "
                f"prices_override.csv for {ticker} covering {year} "
                f"(ticker,date,close_usd)."
            )
        series = PriceSeries(ticker.upper(), closes, splits)
        self._series[key] = series
        return series

    def all_known_splits(self, ticker: str, years):
        """Every split seen across the cached/fetched windows for `ticker`.

        Each yearly window is padded to start the previous November, so a split is visible
        from the series of the year it happened in. Collecting across years lets a lot
        acquired long ago be tested against splits that happened much later.

        Returns (splits, unreadable_years). The second element matters: a year whose prices
        could not be loaded -- offline with a cold cache, say -- is a year whose splits were
        not checked, and silently returning fewer splits would defeat the whole point.
        """
        found: dict[dt.date, Decimal] = {}
        missing: list[int] = []
        for year in years:
            try:
                for day, ratio in self.series(ticker, year).splits:
                    found[day] = ratio
            except PriceError:
                missing.append(year)
        return sorted(found.items()), missing

    # -- cache -------------------------------------------------------------

    def _cache_path(self, ticker: str, year: int) -> str:
        safe = "".join(c for c in ticker.upper() if c.isalnum() or c in "._-")
        return os.path.join(self.cache_dir, f"{safe}_{year}.json")

    def _from_cache(self, ticker: str, year: int):
        path = self._cache_path(ticker, year)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            # Caches written before split support lack the key entirely. Treat those as
            # stale and refetch, so a pre-existing cache cannot hide a split.
            if "splits" not in raw:
                return None
            closes = {
                dt.date.fromisoformat(d): Decimal(str(p))
                for d, p in raw.get("closes", {}).items()
            }
            splits = [
                (dt.date.fromisoformat(d), Decimal(str(r)))
                for d, r in raw.get("splits", {}).items()
            ]
            return closes, splits
        except Exception:
            return None

    def _to_cache(self, ticker: str, year: int, closes: dict[dt.date, Decimal],
                  splits: list[tuple[dt.date, Decimal]]) -> None:
        path = self._cache_path(ticker, year)
        payload = {
            "ticker": ticker.upper(),
            "year": year,
            "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": "yahoo-chart-v8",
            "closes": {d.isoformat(): str(p) for d, p in sorted(closes.items())},
            "splits": {d.isoformat(): str(r) for d, r in sorted(splits)},
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)

    # -- fetch -------------------------------------------------------------

    def _fetch(
        self, ticker: str, year: int
    ) -> tuple[dict[dt.date, Decimal], list[tuple[dt.date, Decimal]]]:
        # Pad the window: we need a close on or before 1 Jan to value a holding that
        # existed before the year began, and Yahoo's window edges are inclusive-ish.
        start = dt.datetime(year - 1, 11, 1, tzinfo=dt.timezone.utc)
        end = dt.datetime(year + 1, 1, 15, tzinfo=dt.timezone.utc)
        params = {
            "period1": int(start.timestamp()),
            "period2": int(end.timestamp()),
            "interval": "1d",
            # Ask for corporate actions; splits are what make or break the valuation.
            "events": "div,split",
        }
        resp = requests.get(
            YAHOO_CHART_URL.format(ticker=ticker),
            params=params,
            headers=_HEADERS,
            timeout=45,
        )
        resp.raise_for_status()
        payload = resp.json()
        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise PriceError(f"Yahoo error for {ticker}: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise PriceError(f"Yahoo returned no data for {ticker}")
        result = results[0]
        stamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        closes_raw = quote.get("close") or []
        # Yahoo stamps each daily bar at the exchange's opening instant in UTC. Shifting
        # by the exchange's own GMT offset recovers the local trading date, which is what
        # a US broker statement would show. Decoding in the local (IST) zone instead
        # would slide every US bar back a day.
        gmtoffset = int(result.get("meta", {}).get("gmtoffset") or 0)
        out: dict[dt.date, Decimal] = {}
        for stamp, close in zip(stamps, closes_raw):
            if close is None:
                continue
            local = dt.datetime.fromtimestamp(stamp + gmtoffset, tz=dt.timezone.utc)
            out[local.date()] = Decimal(str(round(float(close), 6)))
        if not out:
            raise PriceError(f"Yahoo returned only null closes for {ticker}")

        splits: list[tuple[dt.date, Decimal]] = []
        for entry in ((result.get("events") or {}).get("splits") or {}).values():
            try:
                day = dt.datetime.fromtimestamp(
                    int(entry["date"]) + gmtoffset, tz=dt.timezone.utc
                ).date()
                num = Decimal(str(entry["numerator"]))
                den = Decimal(str(entry["denominator"]))
                if den == 0:
                    continue
                splits.append((day, num / den))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        return out, sorted(splits)


def _load_overrides(path: str) -> dict[tuple[str, dt.date], Decimal]:
    if not path or not os.path.exists(path):
        return {}
    out: dict[tuple[str, dt.date], Decimal] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for lineno, row in enumerate(csv.DictReader(fh), start=2):
            ticker = (row.get("ticker") or "").strip().upper()
            date_raw = (row.get("date") or "").strip()
            close_raw = (row.get("close_usd") or "").strip()
            if not ticker or not date_raw or not close_raw:
                continue
            try:
                day = dt.date.fromisoformat(date_raw)
            except ValueError as exc:
                raise PriceError(
                    f"{path} line {lineno}: bad date {date_raw!r}, want YYYY-MM-DD"
                ) from exc
            try:
                out[(ticker, day)] = Decimal(close_raw)
            except Exception as exc:
                raise PriceError(
                    f"{path} line {lineno}: bad close_usd {close_raw!r}"
                ) from exc
    return out
