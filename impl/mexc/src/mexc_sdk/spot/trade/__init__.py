from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk.market import Trading as _Trading
from mexc_sdk.core import SpotMixin, Settings, StreamManager
from .cancel import Cancel
from .place import Place

@_dataclass(frozen=True)
class Trading(SpotMixin, _Trading):
  cancel: Cancel
  place: Place

  @classmethod
  def of(cls, meta: SpotMixin.Meta, *, client: MEXC, settings: Settings = {}, streams: dict[str, StreamManager] = {}):
    return cls(
      meta=meta, client=client, settings=settings, streams=streams,
      cancel=Cancel.of(meta=meta, client=client, settings=settings, streams=streams),
      place=Place.of(meta=meta, client=client, settings=settings, streams=streams),
    )