from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk import PerpMarket as _PerpMarket

from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True)
class Futures(_PerpMarket):
  data: MarketData
  trade: Trading
  user: UserData

  @classmethod
  def new(
    cls, instrument: str, client: MEXC, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    return cls(
      data=MarketData.new(instrument, client, validate=validate, recvWindow=recvWindow),
      trade=Trading.new(instrument, client, validate=validate, recvWindow=recvWindow),
      user=UserData.new(instrument, client, validate=validate, recvWindow=recvWindow),
    )
