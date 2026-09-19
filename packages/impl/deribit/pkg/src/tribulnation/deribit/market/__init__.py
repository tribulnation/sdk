"""Credential-free Deribit public spot and linear perpetual Market support."""

from tribulnation.sdk.market import TradingVenue
from .common import Public, Shared
from .exchanges import SpotExchange, LinearPerpExchange


class DeribitMarket(Public, TradingVenue):
  """Mainnet public data, independent of credentials on private SDK surfaces."""

  @classmethod
  def new(cls, *, validate: bool = True):
    """Construct only a credential-free mainnet client."""
    return cls(shared=Shared.new(public=True, validate=validate))

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """Expose native spot and supported linear perpetual product identities."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'perp', 'type': 'perp', 'name': 'Linear Perpetuals'},
    ]

  async def exchange(self, exchange_id: str, /) -> SpotExchange | LinearPerpExchange:
    """Reject unknown exchange IDs rather than redirecting them."""
    if exchange_id == 'spot':
      return SpotExchange(shared=self.shared)
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> LinearPerpExchange:
    """Only perp denotes supported linear perpetuals."""
    if exchange_id != 'perp':
      raise ValueError(f'Unknown Deribit perpetual exchange: {exchange_id}')
    return LinearPerpExchange(shared=self.shared)
