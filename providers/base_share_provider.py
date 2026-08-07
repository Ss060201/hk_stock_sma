"""Base abstractions for turnover share-base providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ShareBaseLookupResult:
    """Resolved share-base information for turnover-rate calculations."""

    ticker: str
    share_base: Optional[int]
    method: Optional[str]
    warning: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[str] = None


class BaseShareProvider(ABC):
    """Abstract provider for turnover share-base resolution."""

    @abstractmethod
    def get_share_base(self, ticker_obj: Any) -> ShareBaseLookupResult:
        """Resolve the turnover denominator for a ticker or ticker object."""
