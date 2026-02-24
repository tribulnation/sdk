from typing_extensions import overload as _overload
from dataclasses import dataclass as _dataclass

from mexc_sdk.core import Mixin, Settings, spot_name, perp_name
from .earn import Earn
from .spot import Spot
from .wallet import Wallet
from .futures import Futures

@_dataclass(frozen=True)
class MEXC(Mixin):

  @_overload
  async def spot(self, base: str, quote: str, /, *, settings: Settings = {}, refetch: bool = False) -> Spot: ...
  @_overload
  async def spot(self, instrument: str, /, *, settings: Settings = {}, refetch: bool = False) -> Spot: ...
  async def spot(
    self, first: str, second: str | None = None, *,
    settings: Settings = {}, refetch: bool = False,
  ) -> Spot:
    if second is None:
      instrument = first
    else:
      instrument = spot_name(first, second)
    info = await self.cached_spot_market(instrument, refetch=refetch)
    return Spot.of(meta={'info': info}, client=self.client, settings=settings, streams=self.streams)

  @_overload
  async def perp(self, base: str, quote: str, /, *, settings: Settings = {}, refetch: bool = False) -> Futures: ...
  @_overload
  async def perp(self, instrument: str, /, *, settings: Settings = {}, refetch: bool = False) -> Futures: ...
  async def perp(
    self, first: str, second: str | None = None, *,
    settings: Settings = {}, refetch: bool = False,
  ) -> Futures:
    if second is None:
      instrument = first
    else:
      instrument = perp_name(first, second)
    info = await self.cached_perp_market(instrument, refetch=refetch)
    return Futures.of(meta={'info': info}, client=self.client, settings=settings, streams=self.streams)


  @property
  def earn(self) -> Earn:
    return Earn(client=self.client, settings=self.settings, streams=self.streams)

  @property
  def wallet(self) -> Wallet:
    return Wallet(client=self.client, settings=self.settings, streams=self.streams)