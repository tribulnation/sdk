from dataclasses import dataclass as _dataclass

from mexc import MEXC

from tribulnation.sdk.market import PerpUserData as _PerpUserData

from .balances import Balances
from .position import Position
from .trades import Trades
from .orders import Orders
from .funding import Funding

@_dataclass(frozen=True)
class UserData(_PerpUserData):
  balances: Balances
  position: Position
  trades: Trades
  orders: Orders
  funding: Funding

  @classmethod
  def new(
    cls, instrument: str, client: MEXC, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    return cls(
      balances=Balances(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
      position=Position(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
      trades=Trades(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
      orders=Orders(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
      funding=Funding(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
    )
