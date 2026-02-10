import os
from dataclasses import dataclass as _dataclass, field as _field

from dydx.indexer import Indexer as _Indexer
from dydx.node import PrivateNode as _PrivateNode

from .market import Market

@_dataclass(kw_only=True)
class DYDX:
  address: str
  subaccount: int = 0
  indexer: _Indexer = _field(default_factory=_Indexer.new)
  node: _PrivateNode

  @classmethod
  async def connect(
    cls, *, address: str | None = None, subaccount: int = 0, mnemonic: str | None = None, validate: bool = True
  ):
    if address is None:
      address = os.environ['DYDX_ADDRESS']
    indexer = _Indexer.new(validate=validate)
    node = await _PrivateNode.connect(mnemonic)
    return cls(address=address, subaccount=subaccount, indexer=indexer, node=node)

  def market(self, market: str) -> Market:
    return Market(market=market, address=self.address, subaccount=self.subaccount, indexer=self.indexer, node=self.node)