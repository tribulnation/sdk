from dataclasses import dataclass as _dataclass

from mexc import MEXC
from mexc.spot.market_data.exchange_info import Info

from trading_sdk.market import MarketData as _MarketData
from .depth import Depth
from .rules import Rules

@_dataclass(frozen=True)
class MarketData(_MarketData):
  depth: Depth
  rules: Rules

  @classmethod
  def new(
    cls, instrument: Info, client: MEXC, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    return cls(
      depth=Depth(client, info=instrument, validate=validate, recvWindow=recvWindow),
      rules=Rules(client, info=instrument, validate=validate, recvWindow=recvWindow)
    )