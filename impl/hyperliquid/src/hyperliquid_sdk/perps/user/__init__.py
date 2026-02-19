from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpUserData
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid_sdk.perps.core import Meta, PerpMixin
from .balances import Balances
from .funding import Funding
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(PerpMixin, PerpUserData):
  Balances = Balances
  Funding = Funding
  Orders = Orders
  Position = Position
  Trades = Trades
  balances: Balances
  funding: Funding
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def of(cls, *, address: str, client: _Hyperliquid, validate: bool = True, meta: Meta):
    return cls(
      address=address, client=client, validate=validate, meta=meta,
      balances=Balances(address=address, client=client, validate=validate, meta=meta),
      funding=Funding(address=address, client=client, validate=validate, meta=meta),
      orders=Orders(address=address, client=client, validate=validate, meta=meta),
      position=Position(address=address, client=client, validate=validate, meta=meta),
      trades=Trades(address=address, client=client, validate=validate, meta=meta),
    )