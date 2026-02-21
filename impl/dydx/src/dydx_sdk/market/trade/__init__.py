from dataclasses import dataclass as _dataclass

from trading_sdk.market import Trading as _Trading
from dydx_sdk.core import Mixin as _Mixin
from .cancel import Cancel
from .place import Place

@_dataclass(frozen=True)
class Trading(_Trading):
  cancel: Cancel
  place: Place

  @classmethod
  def of(cls, base: _Mixin):
    return cls(
      cancel=Cancel.of(base),
      place=Place.of(base),
    )
