"""yfinance-backed turnover share-base provider."""

from __future__ import annotations

from typing import Any

from providers.base_share_provider import BaseShareProvider, ShareBaseLookupResult


class YahooShareBaseProvider(BaseShareProvider):
    """Resolve turnover share base from Yahoo Finance sharesOutstanding."""

    def get_share_base(self, ticker_obj: Any) -> ShareBaseLookupResult:
        ticker = self._normalize_ticker(getattr(ticker_obj, "ticker", ticker_obj))
        info = {}
        try:
            info = ticker_obj.info or {}
        except Exception:
            info = {}

        share_base = self._normalize_share_base(info.get("sharesOutstanding"))
        if share_base is not None:
            return ShareBaseLookupResult(
                ticker=ticker,
                share_base=share_base,
                method="shares_outstanding",
                source="yfinance",
                confidence="medium",
            )

        return ShareBaseLookupResult(
            ticker=ticker,
            share_base=None,
            method=None,
            warning=f"No sharesOutstanding available from Yahoo Finance for ticker {ticker}.",
            source="yfinance",
            confidence="low",
        )

    @staticmethod
    def _normalize_ticker(ticker: object) -> str:
        raw = str(ticker or "").strip().upper().replace(" ", "")
        if raw.endswith(".HK"):
            raw = raw[:-3]
        if raw.isdigit():
            return f"{int(raw):04d}"
        return raw

    @staticmethod
    def _normalize_share_base(value: object) -> int | None:
        try:
            if value is None:
                return None
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return None
        return int(number)
