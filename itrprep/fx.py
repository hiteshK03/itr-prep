"""SBI TT (telegraphic transfer) buying rates for USD -> INR.

Schedule FA must be converted at the SBI TT buying rate on specific dates -- see
docs/VERIFIED_FINDINGS.md section 10 for the ITD sentence that establishes this.

Rates come from sahilgupta/sbi-fx-ratekeeper, which scrapes SBI's daily published rate
cards into CSV. The CSV is cached locally so that filing-time runs need no network.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
from decimal import Decimal

import requests

SBI_CSV_URL = (
    "https://raw.githubusercontent.com/sahilgupta/sbi-fx-ratekeeper/"
    "main/csv_files/SBI_REFERENCE_RATES_USD.csv"
)

TT_BUY_COLUMN = "TT BUY"
DATE_COLUMN = "DATE"


class FxError(Exception):
    pass


class FxRates:
    """Date -> USD/INR TT buying rate, with carry-forward for non-publication days.

    Two wrinkles in the upstream data that are handled here:

    1. SBI sometimes publishes more than one card in a day (a morning rate and a revised
       afternoon rate). 12 of ~1,600 dates in the file are like this. We take the
       FIRST card of the day, so a given date always maps to one reproducible number.
    2. Some rows carry a TT BUY of 0.00 -- SBI published a card that day but without TT
       rates. Zero is treated as missing, not as a rate of zero.
    """

    def __init__(self, rates: dict[dt.date, Decimal]):
        if not rates:
            raise FxError("no FX rates loaded")
        self._rates = rates
        self._sorted_dates = sorted(rates)

    @classmethod
    def load(cls, cache_path: str) -> FxRates:
        if not os.path.exists(cache_path):
            raise FxError(
                f"FX rate cache not found at {cache_path}.\n"
                f"Run:  itr-prep fx-update\n"
                f"(that downloads SBI TT buying rates once and caches them locally)"
            )
        rates: dict[dt.date, Decimal] = {}
        with open(cache_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or TT_BUY_COLUMN not in reader.fieldnames:
                raise FxError(
                    f"{cache_path} has no '{TT_BUY_COLUMN}' column "
                    f"(found: {reader.fieldnames}). Re-run: itr-prep fx-update"
                )
            for row in reader:
                stamp = (row.get(DATE_COLUMN) or "").strip()
                if not stamp:
                    continue
                try:
                    day = dt.date.fromisoformat(stamp[:10])
                except ValueError:
                    continue
                raw = (row.get(TT_BUY_COLUMN) or "").strip()
                if not raw:
                    continue
                try:
                    rate = Decimal(raw)
                except Exception:
                    continue
                if rate <= 0:
                    continue
                # First card of the day wins; later revisions are ignored.
                rates.setdefault(day, rate)
        return cls(rates)

    @staticmethod
    def update(cache_path: str, timeout: int = 60) -> tuple[int, dt.date, dt.date]:
        """Download the rate CSV to `cache_path`. Returns (rows, earliest, latest)."""
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        resp = requests.get(SBI_CSV_URL, timeout=timeout)
        resp.raise_for_status()
        tmp = cache_path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(resp.content)
        # Only replace the good cache if the download actually parses.
        probe = FxRates.load(tmp)
        os.replace(tmp, cache_path)
        return len(probe._rates), probe._sorted_dates[0], probe._sorted_dates[-1]

    def rate_on(self, day: dt.date) -> tuple[Decimal, dt.date]:
        """TT buying rate applicable to `day`, carrying the last published rate forward.

        Weekends, Indian bank holidays and days SBI published no TT rate have no card of
        their own. The ITD gives no rule for this, so we use the most recent published
        rate on or before the date, which is the standard practitioner treatment and is
        never a rate the taxpayer could not have obtained on that date.

        Returns the rate and the date it was actually published, so callers can show the
        substitution in the audit trail.
        """
        if day in self._rates:
            return self._rates[day], day
        candidates = [d for d in self._sorted_dates if d <= day]
        if not candidates:
            raise FxError(
                f"no SBI TT buying rate on or before {day}; the cached data starts at "
                f"{self._sorted_dates[0]}. Run: itr-prep fx-update"
            )
        chosen = candidates[-1]
        return self._rates[chosen], chosen

    def coverage(self) -> tuple[dt.date, dt.date, int]:
        return self._sorted_dates[0], self._sorted_dates[-1], len(self._sorted_dates)

    def assert_covers_year(self, year: int) -> None:
        """Fail loudly if the cache cannot value a 31 December closing balance."""
        first, last, _ = self.coverage()
        year_end = dt.date(year, 12, 31)
        if last < year_end:
            raise FxError(
                f"FX cache ends {last}, which is before {year_end}. The closing balance "
                f"for calendar {year} cannot be converted. Run: itr-prep fx-update"
            )
        if first > dt.date(year, 1, 1):
            raise FxError(
                f"FX cache starts {first}, after 1 Jan {year}. Run: itr-prep fx-update"
            )
