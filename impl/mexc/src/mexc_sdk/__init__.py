from typing_extensions import overload as _overload
from dataclasses import dataclass as _dataclass, field as _field

from mexc_sdk.core import SdkMixin, spot_name, perp_name
from .earn import Earn
from .spot import Spot
from .wallet import Wallet
from .futures import Futures

@_dataclass
class MEXC(SdkMixin):
  earn: Earn = _field(init=False)
  wallet: Wallet = _field(init=False)

  @_overload
  async def spot(self, base: str, quote: str, /) -> Spot: ...
  @_overload
  async def spot(self, instrument: str, /) -> Spot: ...
  async def spot(self, base: str | None = None, quote: str | None = None, instrument: str | None = None) -> Spot:
    if base is not None and quote is not None:
      instrument = spot_name(base, quote)
    elif instrument is None:
      raise ValueError('Either base and quote or instrument must be provided')

    info = (await self.client.spot.exchange_info(instrument))[instrument]
    return Spot.new(info, self.client, validate=self.validate)

  @_overload
  def perp(self, base: str, quote: str, /) -> Futures: ...
  @_overload
  def perp(self, instrument: str, /) -> Futures: ...
  def perp(self, base: str | None = None, quote: str | None = None, instrument: str | None = None) -> Futures:
    if base is not None and quote is not None:
      instrument = perp_name(base, quote)
    elif instrument is None:
      raise ValueError('Either base and quote or instrument must be provided')

    return Futures.new(instrument, self.client, validate=self.validate)

  def __post_init__(self):
    self.earn = Earn(self.client, validate=self.validate)
    self.wallet = Wallet(self.client, validate=self.validate)