from dataclasses import dataclass as _dataclass

from hyperliquid_sdk.core import Mixin as _Mixin
from .spot import Spot, SpotMarket
from .perps import Perp, PerpMarket


@_dataclass(frozen=True)
class Hyperliquid(_Mixin):
  async def spot(self):
    return await Spot.fetch(address=self.address, client=self.client, validate=self.validate)

  async def perp(self):
    return await Perp.fetch(address=self.address, client=self.client, validate=self.validate)