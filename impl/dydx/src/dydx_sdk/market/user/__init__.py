from dataclasses import dataclass as _dataclass

from dydx.indexer import Indexer as _Indexer

from tribulnation.sdk.market import PerpUserData
from .balances import Balances
from .funding import Funding
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(PerpUserData):
  balances: Balances
  funding: Funding
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def new(
    cls, market: str, *,
    address: str,
    subaccount: int = 0,
    indexer: _Indexer | None = None,
  ):
    indexer = indexer or _Indexer.new()
    return cls(
      balances=Balances(market=market, indexer_data=indexer.data, address=address, subaccount=subaccount),
      funding=Funding(market=market, indexer_data=indexer.data, address=address, subaccount=subaccount),
      orders=Orders(market=market, indexer_data=indexer.data, address=address, subaccount=subaccount),
      position=Position(market=market, indexer_data=indexer.data, address=address, subaccount=subaccount),
      trades=Trades(market=market, indexer_data=indexer.data, indexer_streams=indexer.streams, address=address, subaccount=subaccount),
    )
