from dataclasses import dataclass as _dataclass

from mexc import MEXC
from mexc.spot.market_data.exchange_info import Info

from trading_sdk.market import UserData as _UserData
from .balances import Balances
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(_UserData):
  balances: Balances
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def new(
    cls, instrument: Info, client: MEXC, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    return cls(
      balances=Balances(client, info=instrument, validate=validate, recvWindow=recvWindow),
      orders=Orders(client, info=instrument, validate=validate, recvWindow=recvWindow),
      position=Position(client, info=instrument, validate=validate, recvWindow=recvWindow),
      trades=Trades(client, info=instrument, validate=validate, recvWindow=recvWindow),
    )