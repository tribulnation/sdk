from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk.market import Trading as _Trading
from mexc_sdk.core import PerpMixin, Settings
from .place import Place
from .cancel import Cancel

@_dataclass(frozen=True)
class Trading(PerpMixin, _Trading):
  place: Place
  cancel: Cancel

  @classmethod
  def of(cls, meta: PerpMixin.Meta, *, client: MEXC, settings: Settings = {}):
    return cls(
      meta=meta, client=client, settings=settings,
      place=Place.of(meta=meta, client=client, settings=settings),
      cancel=Cancel.of(meta=meta, client=client, settings=settings),
    )
