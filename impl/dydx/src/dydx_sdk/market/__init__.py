import os
from dataclasses import dataclass as _dataclass, field as _field

from dydx.indexer import Indexer as _Indexer
from dydx.node import PrivateNode as _PrivateNode

from tribulnation.sdk.market import Market as _Market

from .market_data import MarketData
from .trading import Trading
from .user_data import UserData
from .user_streams import UserStreams

@_dataclass(kw_only=True)
class Market(_Market):
  market: str
  address: str
  subaccount: int = 0
  indexer: _Indexer = _field(default_factory=_Indexer.new)
  node: _PrivateNode

  @property
  def market_streams(self):
    raise NotImplementedError

  @classmethod
  async def connect(
    cls, market: str, *, address: str | None = None, subaccount: int = 0, mnemonic: str | None = None, validate: bool = True
  ):
    if address is None:
      address = os.environ['DYDX_ADDRESS']
    indexer = _Indexer.new(validate=validate)
    node = await _PrivateNode.connect(mnemonic)
    return cls(market=market, address=address, subaccount=subaccount, indexer=indexer, node=node)
  

  @property
  def market_data(self) -> MarketData:
    return MarketData(market=self.market, indexer_data=self.indexer.data)

  @property
  def trading(self) -> Trading:
    return Trading(address=self.address, market=self.market, node=self.node, indexer_data=self.indexer.data)

  @property
  def user_data(self) -> UserData:
    return UserData(market=self.market, address=self.address, subaccount=self.subaccount, indexer_data=self.indexer.data)

  @property
  def user_streams(self) -> UserStreams:
    return UserStreams(market=self.market, address=self.address, subaccount=self.subaccount, indexer_streams=self.indexer.streams)