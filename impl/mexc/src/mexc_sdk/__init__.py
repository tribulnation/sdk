from typing_extensions import overload as _overload
from dataclasses import dataclass as _dataclass, field as _field

from mexc_sdk.core import Mixin, Settings, spot_name, perp_name
from .earn import Earn
from .spot import Spot
from .wallet import Wallet
from .futures import Futures

@_dataclass(frozen=True)
class MEXC(Mixin):

  @_overload
  async def spot(self, base: str, quote: str, /, *, settings: Settings = {}) -> Spot: ...
  @_overload
  async def spot(self, instrument: str, /, *, settings: Settings = {}) -> Spot: ...
  async def spot(
    self,
    base: str | None = None, quote: str | None = None,
    instrument: str | None = None,
    *,
    settings: Settings = {},
  ) -> Spot:
    if base is not None and quote is not None:
      instrument = spot_name(base, quote)
    elif instrument is None:
      raise ValueError('Either base and quote or instrument must be provided')

    info = (await self.client.spot.exchange_info(instrument))[instrument]
    return Spot.of(meta={'info': info}, client=self.client, settings=settings, streams=self.streams)

  @_overload
  async def perp(self, base: str, quote: str, /, *, settings: Settings = {}) -> Futures: ...
  @_overload
  async def perp(self, instrument: str, /, *, settings: Settings = {}) -> Futures: ...
  async def perp(
    self,
    base: str | None = None, quote: str | None = None,
    instrument: str | None = None,
    *,
    settings: Settings = {},
  ) -> Futures:
    if base is not None and quote is not None:
      instrument = perp_name(base, quote)
    elif instrument is None:
      raise ValueError('Either base and quote or instrument must be provided')

    info = await self.client.futures.contract_info(instrument)
    return Futures.of(meta={'info': info}, client=self.client, settings=settings, streams=self.streams)


  @property
  def earn(self) -> Earn:
    return Earn(client=self.client, settings=self.settings, streams=self.streams)

  @property
  def wallet(self) -> Wallet:
    return Wallet(client=self.client, settings=self.settings, streams=self.streams)