"""Composite turnover share-base provider."""

from __future__ import annotations

from typing import Any, Iterable

from providers.base_share_provider import BaseShareProvider, ShareBaseLookupResult


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
