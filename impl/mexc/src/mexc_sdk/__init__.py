from dataclasses import dataclass as _dataclass

from mexc_sdk.core import Mixin as _Mixin
from .market import MexcMarket, Settings
from .earn import Earn
from .wallet import Wallet

@_dataclass(frozen=True)
class MEXC(_Mixin):

  @property
  def earn(self) -> Earn:
    return Earn(client=self.client, settings=self.settings, streams=self.streams)

  @property
  def wallet(self) -> Wallet:
    return Wallet(client=self.client, settings=self.settings, streams=self.streams)