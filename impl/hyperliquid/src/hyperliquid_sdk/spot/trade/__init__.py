from dataclasses import dataclass as _dataclass

from trading_sdk.market import Trading as _Trading
from hyperliquid_sdk.spot.core import SpotMixin
from .cancel import Cancel
from .place import Place

@_dataclass(frozen=True)
class Trading(SpotMixin, _Trading):
  Cancel = Cancel
  Place = Place
  cancel: Cancel
  place: Place

  @classmethod
  def of(cls, other: 'SpotMixin'):
    return cls(
      address=other.address,
      client=other.client,
      settings=other.settings,
      streams=other.streams,
      meta=other.meta,
      cancel=Cancel.of(other),
      place=Place.of(other),
    )