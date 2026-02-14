from dataclasses import dataclass as _dataclass

from dydx.indexer import IndexerData as _IndexerData
from dydx.node import PublicNode as _PublicNode

from tribulnation.sdk.market_v2 import PerpUserData
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
    indexer_data: _IndexerData | None = None,
  ):
    indexer_data = indexer_data or _IndexerData()
    return cls(
      balances=Balances(market=market, indexer_data=indexer_data, address=address, subaccount=subaccount),
      funding=Funding(market=market, indexer_data=indexer_data, address=address, subaccount=subaccount),
      orders=Orders(market=market, indexer_data=indexer_data, address=address, subaccount=subaccount),
      position=Position(market=market, indexer_data=indexer_data, address=address, subaccount=subaccount),
      trades=Trades(market=market, indexer_data=indexer_data, address=address, subaccount=subaccount),
    )
