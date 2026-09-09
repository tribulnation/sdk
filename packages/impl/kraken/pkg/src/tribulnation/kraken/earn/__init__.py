"""Kraken's Earn surface: the strategy catalogue."""

from tribulnation.sdk.earn import Earn as _Earn
from .instruments import Instruments


class Earn(_Earn, Instruments):
  """Kraken implementation of `Earn`."""
