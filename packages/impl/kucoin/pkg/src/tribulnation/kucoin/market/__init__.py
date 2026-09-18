"""KuCoin's public Classic spot and linear perpetual Market surface."""

from tribulnation.sdk.market import TradingVenue
from .common import Public, Shared
from .exchanges import LinearPerpExchange, SpotExchange


class KucoinMarket(Public, TradingVenue):
  """Public market data with explicit unsupported private trading methods."""

  @classmethod
  def new(cls, *, validate: bool = True):
    """Construct a credential-free client regardless of credential environment variables."""
    return cls(shared=Shared.new(public=True, validate=validate))

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """Expose explicit product identities for spot and linear perpetuals."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Classic Spot'},
      {'id': 'perp', 'type': 'perp', 'name': 'Classic Linear Perpetuals'},
    ]

  async def exchange(self, exchange_id: str, /) -> SpotExchange | LinearPerpExchange:
    """Reject unknown exchange IDs instead of redirecting them."""
    if exchange_id == 'spot':
      return SpotExchange(shared=self.shared)
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> LinearPerpExchange:
    """Only the perp exchange ID denotes supported perpetuals."""
    if exchange_id != 'perp':
      raise ValueError(f'Unknown KuCoin perpetual exchange: {exchange_id}')
    return LinearPerpExchange(shared=self.shared)
