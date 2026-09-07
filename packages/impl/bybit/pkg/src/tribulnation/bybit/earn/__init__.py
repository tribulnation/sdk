from dataclasses import dataclass as _dataclass

from tribulnation.sdk.earn import Earn as _Earn
from .instruments import Instruments


@_dataclass(kw_only=True, frozen=True)
class Earn(_Earn, Instruments):
  """Bybit's Earn surface."""
