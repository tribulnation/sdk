"""Bit2Me as a trading venue: one spot exchange, and nothing else."""

from typing_extensions import Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from .impl import SharedMixin
from .spot_exchange import SpotExchange


@dataclass(frozen=True, kw_only=True)
class Bit2MeMarket(SharedMixin, TradingVenue):
  """Bit2Me implementation of `TradingVenue`.

  Spot is the only exchange: Bit2Me has no derivatives product, so there is no perp
  exchange to ask for.
  """

  @property
  def venue_id(self) -> str:
    return 'bit2me'

  async def exchange(self, exchange_id: str, /) -> SpotExchange:
    if exchange_id != 'spot':
      raise ValueError(f'Invalid exchange ID: {exchange_id}. Only "spot" is supported.')
    return SpotExchange(shared=self.shared)

  async def exchanges(self) -> Sequence[TradingVenue.ExchangeDescription]:
    return [{'id': 'spot', 'type': 'spot', 'name': 'Spot'}]
