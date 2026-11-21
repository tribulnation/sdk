"""Bitget spot, spot margin and two perpetual product lines over one shared client."""

from datetime import timedelta
from dataclasses import dataclass

from tribulnation.sdk.market import Collateral, TradingVenue

from .impl import VenueMixin
from .impl.parse import PERP, PERP_PRODUCTS, perp_exchange_id
from .margin_exchange import MarginExchange
from .perp_exchange import PerpExchange
from .spot_exchange import SpotExchange


@dataclass(kw_only=True, frozen=True)
class BitgetMarket(VenueMixin, TradingVenue):
  """Bitget's spot, UTA spot-margin (`margin`) and USDT- and USDC-margined perpetual
  exchanges.

  Public market data comes from the venue's public endpoints and is the same whatever
  the account's mode; account-scoped reads dispatch on the mode -- Classic or Unified
  Trading Account (UTA) -- which is auto-detected on first use unless `uta` was given.
  Exchanges share one connection and product-keyed caches and streams. USDC futures currently expose public market data only.
  """

  async def exchange(
    self, exchange_id: str, /
  ) -> SpotExchange | MarginExchange | PerpExchange:
    """Resolve `spot`, `margin`, `usdt`, or `usdc`."""
    if exchange_id == 'coin-classic':
      raise NotImplementedError('Bitget Classic coin futures retired on 2026-09-17.')
    if exchange_id == 'coin':
      raise NotImplementedError('Bitget UTA coin markets are deferred: SDK issue #32.')
    if exchange_id == 'spot':
      return SpotExchange(account=self.account, cache=self.cache)
    if exchange_id == 'margin':
      return MarginExchange(account=self.account, cache=self.cache)
    if exchange_id in PERP_PRODUCTS:
      return await self.perp_exchange(exchange_id)
    raise ValueError(
      f'Invalid exchange ID: {exchange_id!r}. Expected spot, margin, usdt or usdc.'
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
    """List available exchanges: spot, UTA cross spot margin and the perpetuals."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'margin', 'type': 'margin', 'name': 'Spot Margin'},
      {'id': 'usdt', 'type': 'perp', 'name': 'USDT Perpetuals'},
      {'id': 'usdc', 'type': 'perp', 'name': 'USDC Perpetuals'},
    ]

  async def collateral(self, id: str, /, *, ttl: timedelta | None = None) -> Collateral:
    """Resolve a collateral ID, without its account key.

    `margin` is the unified pool, the same money as `usdt`: both resolve to it, so a
    caller reserving under either sees the same figures. Everything else resolves as
    `TradingVenue.collateral` does.
    """
    if id == 'margin':
      id = perp_exchange_id(PERP)
    return await super().collateral(id, ttl=ttl)
