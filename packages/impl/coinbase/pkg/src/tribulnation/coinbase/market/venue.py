"""Coinbase as a trading venue: two Advanced Trade exchanges over one client."""

from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from . import impl
from .perp_exchange import PerpExchange
from .spot_exchange import SpotExchange


@dataclass(frozen=True, kw_only=True)
class CoinbaseMarket(impl.ExchangeMixin, TradingVenue):
  """Coinbase's trading surface: `spot` and `intx`.

  Both are served by the same Advanced Trade endpoints and the same credentials; they
  are separate exchanges here because they price under separate fee schedules and,
  for INTX, separate portfolio permissions.
  """

  @property
  def venue_id(self) -> str:
    return impl.VENUE_ID

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    return [
      {'id': impl.SPOT_EXCHANGE_ID, 'type': 'spot', 'name': 'Advanced Trade'},
      {'id': impl.INTX_EXCHANGE_ID, 'type': 'perp', 'name': 'International Exchange'},
    ]

  async def exchange(self, exchange_id: str, /):
    if exchange_id == impl.SPOT_EXCHANGE_ID:
      return SpotExchange(shared=self.shared)
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    if exchange_id != impl.INTX_EXCHANGE_ID:
      raise ValueError(
        f'Unknown Coinbase perpetual exchange "{exchange_id}"; the only one is '
        f'"{impl.INTX_EXCHANGE_ID}".'
      )
    return PerpExchange(shared=self.shared)
