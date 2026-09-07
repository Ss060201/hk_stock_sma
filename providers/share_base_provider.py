"""Composite turnover share-base provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from providers.base_float_provider import BaseFloatProvider
from providers.base_share_provider import BaseShareProvider, ShareBaseLookupResult
from providers.csv_float_provider import CSVFloatProvider
from providers.csv_share_base_provider import CSVShareBaseProvider
from providers.yfinance_share_base_provider import YahooShareBaseProvider


class FloatProviderAsShareProvider(BaseShareProvider):
    """Adapter that exposes a ``BaseFloatProvider`` as a ``BaseShareProvider``.

    CSVFloatProvider is the primary, human-verified source of truth for HK
    float shares (because AASTOCKS "換手率" uses tradable float as its
    denominator, not total shares outstanding). This adapter lets us plug
    CSVFloatProvider at the HEAD of the CompositeShareBaseProvider chain
    without duplicating the lookup contract.
    """

    def __init__(self, float_provider: BaseFloatProvider) -> None:
        self.float_provider = float_provider

    @staticmethod
    def _ticker_str(ticker_obj: Any) -> str:
        ticker = getattr(ticker_obj, "ticker", ticker_obj)
        raw = str(ticker or "").strip().upper().replace(" ", "")
        if raw.endswith(".HK"):
            raw = raw[:-3]
        if raw.isdigit():
            return raw.zfill(4)
        return raw

    def get_share_base(self, ticker_obj: Any) -> ShareBaseLookupResult:
        ticker = self._ticker_str(ticker_obj)
        result = self.float_provider.get_float_shares(ticker)
        return ShareBaseLookupResult(
            ticker=result.ticker,
            share_base=result.share_base,
            method=result.method,
            warning=result.warning,
            source=result.source,
            confidence=result.confidence,
        )


class CompositeShareBaseProvider(BaseShareProvider):
    """Resolve share base by trying providers in priority order."""

    def __init__(self, providers: Iterable[BaseShareProvider]) -> None:
        self.providers = list(providers)

    def get_share_base(self, ticker_obj: Any) -> ShareBaseLookupResult:
        last_result: ShareBaseLookupResult | None = None
        for provider in self.providers:
            result = provider.get_share_base(ticker_obj)
            last_result = result
            if result.share_base is not None:
                return result

        if last_result is not None:
            return last_result

        return ShareBaseLookupResult(
            ticker="",
            share_base=None,
            method=None,
            warning="No share-base provider is configured.",
            source="composite",
            confidence="low",
        )


def build_default_share_base_provider(
    metadata_dir: str | Path | None = None,
) -> CompositeShareBaseProvider:
    """Construct the standard 3-tier provider chain used across all surfaces.

    Priority (AASTOCKS TUR = Volume / 流通股本 float_shares):
      1) CSVFloatProvider  (float.csv, user-maintained overrides)
      2) CSVShareBaseProvider (share_base.csv, legacy overrides)
      3) YahooShareBaseProvider (Ticker.info floatShares > sharesOutstanding > implied)
    """
    if metadata_dir is None:
        metadata_dir = Path(__file__).resolve().parents[1] / "metadata"
    metadata_path = Path(metadata_dir)
    return CompositeShareBaseProvider(
        [
            FloatProviderAsShareProvider(CSVFloatProvider(metadata_path / "float.csv")),
            CSVShareBaseProvider(metadata_path / "share_base.csv"),
            YahooShareBaseProvider(),
        ]
    )
