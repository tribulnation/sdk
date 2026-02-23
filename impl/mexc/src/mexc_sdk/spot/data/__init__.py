from dataclasses import dataclass as _dataclass

from mexc import MEXC

from mexc_sdk.core import Settings, SpotMixin, StreamManager
from trading_sdk.market import MarketData as _MarketData
from .depth import Depth
from .rules import Rules

@_dataclass(frozen=True)
class MarketData(SpotMixin, _MarketData):
  depth: Depth
  rules: Rules

  @classmethod
  def of(cls, meta: SpotMixin.Meta, *, client: MEXC, settings: Settings = {}, streams: dict[str, StreamManager] = {}):
    return cls(
      meta=meta, client=client, settings=settings, streams=streams,
      depth=Depth.of(meta=meta, client=client, settings=settings, streams=streams),
      rules=Rules.of(meta=meta, client=client, settings=settings, streams=streams),
    )