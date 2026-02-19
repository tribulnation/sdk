from dataclasses import dataclass as _dataclass

from trading_sdk.market import UserData as _UserData
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid_sdk.spot.core import Meta, SpotMixin
from .balances import Balances
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(SpotMixin, _UserData):
  Balances = Balances
  Orders = Orders
  Position = Position
  Trades = Trades
  balances: Balances
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def of(cls, *, address: str, client: _Hyperliquid, validate: bool = True, meta: Meta):
    return cls(
      address=address, client=client, validate=validate, meta=meta,
      balances=Balances(address=address, client=client, validate=validate, meta=meta),
      orders=Orders(address=address, client=client, validate=validate, meta=meta),
      position=Position(address=address, client=client, validate=validate, meta=meta),
      trades=Trades(address=address, client=client, validate=validate, meta=meta),
    )