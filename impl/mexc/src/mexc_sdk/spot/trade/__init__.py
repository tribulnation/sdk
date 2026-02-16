from dataclasses import dataclass as _dataclass

from mexc import MEXC
from mexc.spot.market_data.exchange_info import Info

from trading_sdk.market import Trading as _Trading
from .cancel import Cancel
from .place import Place

@_dataclass(frozen=True)
class Trading(_Trading):
  cancel: Cancel
  place: Place

  @classmethod
  def new(
    cls, instrument: Info, client: MEXC, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    return cls(
      cancel=Cancel(client, info=instrument, validate=validate, recvWindow=recvWindow),
      place=Place(client, info=instrument, validate=validate, recvWindow=recvWindow)
    )