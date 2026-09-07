"""Binance Earn surface."""

from tribulnation.sdk.earn import Earn as _Earn
from .instruments import Instruments


class Earn(_Earn, Instruments):
  """Binance Earn surface."""
