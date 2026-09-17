"""Bitget spot and two perpetual product lines over one shared client."""

from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from .impl import VenueMixin
from .impl.parse import PERP_PRODUCTS
from .perp_exchange import PerpExchange
from .spot_exchange import SpotExchange


@dataclass(kw_only=True, frozen=True)
class BitgetMarket(VenueMixin, TradingVenue):
  """Bitget's spot and USDT- and USDC-margined perpetual exchanges.

  Public market data comes from the venue's public endpoints and is the same whatever
  the account's mode; account-scoped reads dispatch on the mode -- Classic or Unified
  Trading Account (UTA) -- which is auto-detected on first use unless `uta` was given.
  Exchanges share one connection and product-keyed caches and streams. USDC futures currently expose public market data only.
  """

  @property
  def venue_id(self) -> str:
    return 'bitget'

  async def exchange(self, exchange_id: str, /) -> SpotExchange | PerpExchange:
    """Resolve `spot`, `usdt`, or `usdc`."""
    if exchange_id == 'coin-classic':
      raise NotImplementedError('Bitget Classic coin futures retired on 2026-09-17.')
    if exchange_id == 'coin':
      raise NotImplementedError('Bitget UTA coin markets are deferred: SDK issue #32.')
    if exchange_id == 'spot':
      return SpotExchange(account=self.account, cache=self.cache)
    if exchange_id in PERP_PRODUCTS:
      return await self.perp_exchange(exchange_id)
    raise ValueError(
      f'Invalid exchange ID: {exchange_id!r}. Expected spot, usdt or usdc.'
    )

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Resolve a futures product without normalizing any market symbols."""
    if exchange_id == 'coin-classic':
      raise NotImplementedError('Bitget Classic coin futures retired on 2026-09-17.')
    if exchange_id == 'coin':
      raise NotImplementedError('Bitget UTA coin markets are deferred: SDK issue #32.')
    if exchange_id not in PERP_PRODUCTS:
      raise ValueError(
        f'Invalid perp exchange ID: {exchange_id!r}. Expected usdt or usdc.'
      )
    return PerpExchange(
      account=self.account, cache=self.cache, product=PERP_PRODUCTS[exchange_id]
    )

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """List available exchanges."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'usdt', 'type': 'perp', 'name': 'USDT Perpetuals'},
      {'id': 'usdc', 'type': 'perp', 'name': 'USDC Perpetuals'},
    ]
