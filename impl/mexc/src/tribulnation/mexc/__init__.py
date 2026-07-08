from dataclasses import dataclass as _dataclass

from tribulnation.mexc.core import Mixin as _Mixin
from .market import MexcMarket
from .earn import Earn
from .wallet import Wallet

@_dataclass(frozen=True)
class MEXC(_Mixin):

  @property
  def earn(self) -> Earn:
    return Earn()

  @property
  def wallet(self) -> Wallet:
    return Wallet(client=self.client, settings=self.settings, streams=self.streams)