"""Coinbase's earn surface."""

from dataclasses import dataclass as _dataclass

from tribulnation.sdk.earn import Earn as _Earn

from .instruments import Instruments


@_dataclass(frozen=True, kw_only=True)
class Earn(_Earn, Instruments):
  """Coinbase's earn surface: `instruments()` only."""
