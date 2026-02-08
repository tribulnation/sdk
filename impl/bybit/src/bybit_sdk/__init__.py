from dataclasses import dataclass as _dataclass, field as _field

from .core import SdkMixin
from .earn import Earn


@_dataclass
class Bybit(SdkMixin):
  earn: Earn = _field(init=False)

  def __post_init__(self):
    self.earn = Earn(self.client)
