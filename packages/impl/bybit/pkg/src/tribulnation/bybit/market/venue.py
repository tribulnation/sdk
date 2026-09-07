"""Bybit as a trading venue: one unified API, two exchanges."""

from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from .impl import VenueMixin
from .perp_exchange import PerpExchange
from .spot_exchange import SpotExchange


@dataclass(kw_only=True, frozen=True)
class BybitMarket(VenueMixin, TradingVenue):
  """Bybit's spot and linear-perpetual exchanges, over one client.

  Bybit v5 is a single API discriminated by a `category` parameter rather than
  separate spot and futures endpoints, so both exchanges here share one connection,
  one instrument cache and one private stream.
  """

  @property
  def venue_id(self) -> str:
    return 'bybit'

  async def exchange(self, exchange_id: str, /) -> SpotExchange | PerpExchange:
    """Resolve an exchange by id: `spot` or `perp`."""
    if exchange_id == 'spot':
      return SpotExchange(client=self.client, settings=self.settings, cache=self.cache)
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
    return PerpExchange(client=self.client, settings=self.settings, cache=self.cache)

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """List available exchanges."""
    return [{'id': 'spot', 'type': 'spot'}, {'id': 'perp', 'type': 'perp'}]
