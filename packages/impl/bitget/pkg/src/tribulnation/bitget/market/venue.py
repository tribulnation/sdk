"""Bitget as a trading venue: one client, two exchanges."""

from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from .impl import VenueMixin
from .perp_exchange import PerpExchange
from .spot_exchange import SpotExchange


@dataclass(kw_only=True, frozen=True)
class BitgetMarket(VenueMixin, TradingVenue):
  """Bitget's spot and USDT-margined perpetual exchanges, over one client.

  Public market data comes from the venue's public endpoints and is the same whatever
  the account's mode; account-scoped reads dispatch on the mode -- Classic or Unified
  Trading Account (UTA) -- which is auto-detected on first use unless `uta` was given.
  Both exchanges share one connection, one catalogue cache and one set of streams.
  """

  @property
  def venue_id(self) -> str:
    return 'bitget'

  async def exchange(self, exchange_id: str, /) -> SpotExchange | PerpExchange:
    """Resolve an exchange by id: `spot` or `perp`."""
    if exchange_id == 'spot':
      return SpotExchange(account=self.account, cache=self.cache)
    if exchange_id == 'perp':
      return await self.perp_exchange(exchange_id)
    raise ValueError(
      f'Invalid exchange ID: {exchange_id!r}. Only "spot" and "perp" are supported.'
    )

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Resolve the perpetual exchange by id: `perp`."""
    if exchange_id != 'perp':
      raise ValueError(
        f'Invalid perp exchange ID: {exchange_id!r}. Only "perp" is supported.'
      )
    return PerpExchange(account=self.account, cache=self.cache)

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """List available exchanges."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'perp', 'type': 'perp', 'name': 'USDT Perpetuals'},
    ]
