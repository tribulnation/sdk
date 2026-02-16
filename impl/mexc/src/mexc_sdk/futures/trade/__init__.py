from dataclasses import dataclass as _dataclass

from mexc import MEXC

from tribulnation.sdk.market import Trading as _Trading

from .place import Place
from .cancel import Cancel

@_dataclass(frozen=True)
class Trading(_Trading):
  place: Place
  cancel: Cancel

  @classmethod
  def new(
    cls, instrument: str, client: MEXC, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    return cls(
      place=Place(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
      cancel=Cancel(client, instrument=instrument, validate=validate, recvWindow=recvWindow),
    )
