"""CSV-backed float-share metadata provider."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, Optional

from providers.base_float_provider import BaseFloatProvider, FloatLookupResult

LOGGER = logging.getLogger(__name__)


class CSVFloatProvider(BaseFloatProvider):
    """Read float-share metadata from a local CSV file.

    The CSV schema is intentionally simple and repository-friendly:
    ``ticker, company, outstanding, float_ratio, float_shares, last_update,
    source, confidence``.

    Fallback order:
    1. ``float_shares``
    2. ``outstanding``
    3. unresolved with warning
    """

    REQUIRED_COLUMNS = {
        "ticker",
        "company",
        "outstanding",
        "float_ratio",
        "float_shares",
        "last_update",
        "source",
        "confidence",
    }

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)
        self._records = self._load_records()

    def get_float_shares(self, ticker: str) -> FloatLookupResult:
        normalized = self._normalize_ticker(ticker)
        record = self._records.get(normalized)
        if not record:
            return FloatLookupResult(
                ticker=normalized,
                share_base=None,
                method=None,
                warning=f"No float metadata found for ticker {normalized}.",
                source="csv",
            )

        confidence = self._clean_text(record.get("confidence"))
        source = self._clean_text(record.get("source")) or "csv"

        float_shares = self._parse_positive_int(record.get("float_shares"))
        if float_shares is not None:
            return FloatLookupResult(
                ticker=normalized,
                share_base=float_shares,
                method="float",
                source=source,
                confidence=confidence,
            )

        outstanding = self._parse_positive_int(record.get("outstanding"))
        if outstanding is not None:
            return FloatLookupResult(
                ticker=normalized,
                share_base=outstanding,
                method="outstanding",
                warning=f"Float shares missing for {normalized}; fell back to outstanding shares.",
                source=source,
                confidence=confidence,
            )

        return FloatLookupResult(
            ticker=normalized,
            share_base=None,
            method=None,
            warning=f"Neither float_shares nor outstanding is available for ticker {normalized}.",
            source=source,
            confidence=confidence,
        )

    def _load_records(self) -> Dict[str, Dict[str, str]]:
        if not self.csv_path.exists():
            LOGGER.warning("Float metadata file not found: %s", self.csv_path)
            return {}

        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = set(reader.fieldnames or [])
            missing = self.REQUIRED_COLUMNS - fieldnames
            if missing:
                raise ValueError(
                    f"Float metadata CSV is missing required columns: {sorted(missing)}"
                )

            records: Dict[str, Dict[str, str]] = {}
            for raw_row in reader:
                if not raw_row:
                    continue
                raw_ticker = raw_row.get("ticker", "")
                normalized = self._normalize_ticker(raw_ticker)
                if not normalized:
                    LOGGER.warning("Skipping float metadata row with empty ticker: %s", raw_row)
                    continue
                records[normalized] = raw_row

        LOGGER.info("Loaded %s float metadata records from %s", len(records), self.csv_path)
        return records

    @staticmethod
    def _normalize_ticker(ticker: object) -> str:
        raw = str(ticker or "").strip().upper()
        if not raw:
            return ""
        if raw.endswith(".HK"):
            raw = raw[:-3]
        if raw.isdigit():
            return raw.zfill(4)
        return raw

    @staticmethod
    def _clean_text(value: object) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _parse_positive_int(value: object) -> Optional[int]:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if number <= 0:
            return None
        return int(number)

