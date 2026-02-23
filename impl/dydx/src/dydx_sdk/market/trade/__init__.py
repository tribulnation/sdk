from dataclasses import dataclass as _dataclass

from trading_sdk.market import Trading as _Trading
from dydx_sdk.core import MarketMixin
from .cancel import Cancel
from .place import Place

@_dataclass(frozen=True)
class Trading(MarketMixin, _Trading):
  cancel: Cancel
  place: Place

  @classmethod
  def of(cls, other: MarketMixin):
    return cls(
      address=other.address,
      indexer=other.indexer,
      public_node=other.public_node,
      private_node=other.private_node,
      streams=other.streams,
      settings=other.settings,
      perpetual_market=other.perpetual_market,
      subaccount=other.subaccount,
      cancel=Cancel.of(other),
      place=Place.of(other),
    )
