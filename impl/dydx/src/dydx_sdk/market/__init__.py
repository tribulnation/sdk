from dataclasses import dataclass as _dataclass, field as _field

from dydx.indexer import Indexer as _Indexer
from dydx.node import PrivateNode as _PrivateNode

from .market_data import MarketData
from .trading import Trading
from .user_data import UserData
from .user_streams import UserStreams

@_dataclass(kw_only=True)
class Market:
  market: str
  address: str
  subaccount: int = 0
  indexer: _Indexer = _field(default_factory=_Indexer.new)
  node: _PrivateNode

  @classmethod
  async def connect(
    cls, market: str, *, address: str, subaccount: int = 0, mnemonic: str, validate: bool = True
  ):
    indexer = _Indexer.new(validate=validate)
    node = await _PrivateNode.connect(mnemonic=mnemonic)
    return cls(market=market, address=address, subaccount=subaccount, indexer=indexer, node=node)
  
  def __post_init__(self):
    self.market_data = MarketData(market=self.market, indexer_data=self.indexer.data)
    self.trading = Trading(address=self.address, market=self.market, node=self.node, indexer_data=self.indexer.data)
    self.user_data = UserData(market=self.market, address=self.address, subaccount=self.subaccount, indexer_data=self.indexer.data)
    self.user_streams = UserStreams(market=self.market, address=self.address, subaccount=self.subaccount, indexer_streams=self.indexer.streams)