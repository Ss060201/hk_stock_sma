"""yfinance-backed turnover share-base provider."""

from __future__ import annotations

from typing import Any

from providers.base_share_provider import BaseShareProvider, ShareBaseLookupResult


class YahooShareBaseProvider(BaseShareProvider):
    """Resolve turnover share base from Yahoo Finance.

    AASTOCKS-style turnover rate uses tradable float (流通股) as the
    denominator because that's what drives liquidity and hence matches the
    "換手" shown on HK quote platforms.

    Resolution priority (to keep TOR numerically aligned with AASTOCKS):
      1. floatShares (流通股本)  <-- primary, matches industry/HK practice
      2. sharesOutstanding (總股本)  <-- fallback when float is unavailable
      3. impliedSharesOutstanding (rare)
    """

    def get_share_base(self, ticker_obj: Any) -> ShareBaseLookupResult:
        ticker = self._normalize_ticker(getattr(ticker_obj, "ticker", ticker_obj))
        info = {}
        try:
            info = ticker_obj.info or {}
        except Exception:
            info = {}

        float_shares = self._normalize_share_base(info.get("floatShares"))
        if float_shares is not None:
            return ShareBaseLookupResult(
                ticker=ticker,
                share_base=float_shares,
                method="float_shares",
                source="yfinance",
                confidence="high",
            )

        shares_out = self._normalize_share_base(info.get("sharesOutstanding"))
        if shares_out is not None:
            return ShareBaseLookupResult(
                ticker=ticker,
                share_base=shares_out,
                method="shares_outstanding",
                source="yfinance",
                confidence="medium",
                warning=(
                    f"No floatShares available for ticker {ticker}; falling "
                    f"back to sharesOutstanding (TOR may be lower than AASTOCKS)."
                ),
            )

        implied = self._normalize_share_base(info.get("impliedSharesOutstanding"))
        if implied is not None:
            return ShareBaseLookupResult(
                ticker=ticker,
                share_base=implied,
                method="implied_shares_outstanding",
                source="yfinance",
                confidence="low",
                warning=(
                    f"Neither floatShares nor sharesOutstanding available "
                    f"for ticker {ticker}; using impliedSharesOutstanding."
                ),
            )

        return ShareBaseLookupResult(
            ticker=ticker,
            share_base=None,
            method=None,
            warning=(
                f"No floatShares, sharesOutstanding or impliedSharesOutstanding "
                f"available from Yahoo Finance for ticker {ticker}."
            ),
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
