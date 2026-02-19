from dataclasses import dataclass as _dataclass

from trading_sdk.market import Trading as _Trading
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid_sdk.perps.core import Meta, PerpMixin
from .cancel import Cancel
from .place import Place

@_dataclass(frozen=True)
class Trading(PerpMixin, _Trading):
  Cancel = Cancel
  Place = Place
  cancel: Cancel
  place: Place

  @classmethod
  def of(cls, *, address: str, client: _Hyperliquid, validate: bool = True, meta: Meta):
    return cls(
      address=address, client=client, validate=validate, meta=meta,
      cancel=Cancel(address=address, client=client, validate=validate, meta=meta),
      place=Place(address=address, client=client, validate=validate, meta=meta),
    )