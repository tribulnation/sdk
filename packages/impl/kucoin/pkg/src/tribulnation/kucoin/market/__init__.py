"""KuCoin's Classic spot and linear perpetual Market surface."""

import os

from typed_kucoin import KuCoin
from tribulnation.sdk.market import TradingVenue
from .common import Public, Shared
from .exchanges import LinearPerpExchange, SpotExchange


class KucoinMarket(Public, TradingVenue):
  """KuCoin Classic spot and linear perpetuals: public data, account reads and trading."""

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    api_passphrase: str | None = None,
    *,
    public: bool | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Create the venue over one client.

    Credentials fall back to `KUCOIN_API_KEY`, `KUCOIN_API_SECRET` and
    `KUCOIN_API_PASSPHRASE`. A sub-account's API key trades that sub-account. One key
    serves both the spot (`api.kucoin.com`) and futures (`api-futures.kucoin.com`)
    hosts, each with its own private WebSocket connection.

    Args:
      api_key: KuCoin API key.
      api_secret: KuCoin API secret.
      api_passphrase: The passphrase chosen when creating the key.
      public: Build a credential-free client for public market data only. `None`
        decides by the credentials: public when none are passed or set, as SDK
        releases before trading support built this venue.
      validate: Validate responses against the typed client's schemas.
      account_id: Root SDK account key, the first segment of every market ID.

    Raises:
      AuthError: `public` is `False` and a credential is neither passed nor set.
    """
    if public is None:
      public = not (
        (api_key or os.environ.get('KUCOIN_API_KEY'))
        and (api_secret or os.environ.get('KUCOIN_API_SECRET'))
        and (api_passphrase or os.environ.get('KUCOIN_API_PASSPHRASE'))
      )
    client = KuCoin.new(
      api_key=api_key,
      api_secret=api_secret,
      api_passphrase=api_passphrase,
      public=public,
      validate=validate,
    )
    return cls(shared=Shared(client=client, account_id=account_id))

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
