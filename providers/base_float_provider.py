"""Base abstractions for float-share metadata providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FloatLookupResult:
    """Resolved share-base information for turnover-rate calculations.

    Attributes:
        ticker: Normalized ticker requested by the caller.
        share_base: The resolved denominator to use in turnover calculations.
        method: Resolution method used. Expected values are ``"float"``,
            ``"outstanding"``, or ``None`` when unresolved.
        warning: Human-readable warning when float or outstanding shares are
            unavailable or invalid.
        source: Metadata source identifier, for example ``"csv"``.
        confidence: Optional confidence label from metadata, if available.
    """

    ticker: str
    share_base: Optional[int]
    method: Optional[str]
    warning: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[str] = None


class BaseFloatProvider(ABC):
    """Abstract provider for float-share metadata."""

    @abstractmethod
    def get_float_shares(self, ticker: str) -> FloatLookupResult:
        """Resolve float-share metadata for a ticker."""

