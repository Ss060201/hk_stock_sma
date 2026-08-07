"""CSV-backed verified override provider for turnover share base."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from providers.base_share_provider import BaseShareProvider, ShareBaseLookupResult

LOGGER = logging.getLogger(__name__)


class CSVShareBaseProvider(BaseShareProvider):
    """Read manually verified share-base overrides from a local CSV file."""

    REQUIRED_COLUMNS = {
        "ticker",
        "issued_shares",
        "source",
        "source_url",
        "last_verified",
        "confidence",
        "notes",
    }

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)
        self._records = self._load_records()

    def get_share_base(self, ticker_obj: Any) -> ShareBaseLookupResult:
        normalized = self._normalize_ticker_from_obj(ticker_obj)
        record = self._records.get(normalized)
        if not record:
            return ShareBaseLookupResult(
                ticker=normalized,
                share_base=None,
                method=None,
                warning=f"No verified share-base override found for ticker {normalized}.",
                source="csv_override",
            )

        share_base = self._parse_positive_int(record.get("issued_shares"))
        if share_base is None:
            return ShareBaseLookupResult(
                ticker=normalized,
                share_base=None,
                method=None,
                warning=f"Verified override for {normalized} does not contain a valid issued_shares value.",
                source=self._clean_text(record.get("source")) or "csv_override",
                confidence=self._clean_text(record.get("confidence")),
            )

        return ShareBaseLookupResult(
            ticker=normalized,
            share_base=share_base,
            method="override",
            source=self._clean_text(record.get("source")) or "csv_override",
            confidence=self._clean_text(record.get("confidence")),
        )

    def _load_records(self) -> Dict[str, Dict[str, str]]:
        if not self.csv_path.exists():
            LOGGER.warning("Share-base override file not found: %s", self.csv_path)
            return {}

        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = set(reader.fieldnames or [])
            missing = self.REQUIRED_COLUMNS - fieldnames
            if missing:
                raise ValueError(
                    f"Share-base override CSV is missing required columns: {sorted(missing)}"
                )

            records: Dict[str, Dict[str, str]] = {}
            for raw_row in reader:
                if not raw_row:
                    continue
                normalized = self._normalize_ticker(raw_row.get("ticker", ""))
                if not normalized:
                    LOGGER.warning("Skipping share-base override row with empty ticker: %s", raw_row)
                    continue
                records[normalized] = raw_row

        LOGGER.info("Loaded %s share-base override records from %s", len(records), self.csv_path)
        return records

    @classmethod
    def _normalize_ticker_from_obj(cls, ticker_obj: Any) -> str:
        ticker = getattr(ticker_obj, "ticker", ticker_obj)
        return cls._normalize_ticker(ticker)

    @staticmethod
    def _normalize_ticker(ticker: object) -> str:
        raw = str(ticker or "").strip().upper().replace(" ", "")
        if raw.endswith(".HK"):
            raw = raw[:-3]
        if raw.isdigit():
            return f"{int(raw):04d}"
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
