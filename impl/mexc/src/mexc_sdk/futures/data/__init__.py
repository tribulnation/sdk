from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk.market import PerpMarketData as _PerpMarketData

from .rules import Rules
from .depth import Depth
from .funding import Funding
from .index import Index

@_dataclass(frozen=True)
class MarketData(_PerpMarketData):
  rules: Rules
  depth: Depth
  funding: Funding
  index: Index

  @classmethod
  def new(
    cls, instrument: str, client: MEXC, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    return cls(
      rules=Rules(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
      depth=Depth(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
      funding=Funding(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
      index=Index(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
    )
