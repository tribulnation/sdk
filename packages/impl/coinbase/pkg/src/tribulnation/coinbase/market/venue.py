"""Coinbase as a trading venue: the Advanced Trade spot exchange."""

from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from . import impl
from .spot_exchange import SpotExchange


@dataclass(frozen=True, kw_only=True)
class CoinbaseMarket(impl.ExchangeMixin, TradingVenue):
  """Coinbase's trading surface: the Advanced Trade `spot` exchange.

  INTX perpetuals are not served: Coinbase retires them on the Advanced Trade API on
  2026-10-01, moving international derivatives to a Deribit-powered gateway (ADR 0031).
  `perp_exchange` therefore keeps the base class's `NotImplementedError`.
  """

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    return [{'id': impl.SPOT_EXCHANGE_ID, 'type': 'spot', 'name': 'Advanced Trade'}]

  async def exchange(self, exchange_id: str, /) -> SpotExchange:
    if exchange_id != impl.SPOT_EXCHANGE_ID:
      raise ValueError(
        f'Unknown Coinbase exchange "{exchange_id}"; the only one is '
        f'"{impl.SPOT_EXCHANGE_ID}".'
      )
    return SpotExchange(shared=self.shared)
