"""Bit2Me's Earn surface: the public yield catalogue."""

from tribulnation.sdk.earn import Earn as _Earn
from .instruments import Instruments


class Earn(_Earn, Instruments):
  """Bit2Me implementation of `Earn`."""
