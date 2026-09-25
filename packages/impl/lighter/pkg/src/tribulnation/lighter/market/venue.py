"""The Lighter trading venue: a `perp` and a `spot` exchange."""

from dataclasses import dataclass

from typed_lighter.core.networks import Network
from tribulnation.sdk.market import TradingVenue

from ..core import Shared
from .common import Public
from .exchanges import LighterPerpExchange, LighterSpotExchange


@dataclass(frozen=True, kw_only=True)
class LighterMarket(Public, TradingVenue):
  """Lighter's perpetual and spot markets, on one account.

  Market ids are the venue's numeric `market_id` (`'0'` is mainnet ETH) and asset ids
  its `asset_id` (`'3'` is USDC): the on-chain identities orders are signed with.
  """

  @classmethod
  def new(
    cls,
    account_index: int | None = None,
    api_key_index: int | None = None,
    api_private_key: str | None = None,
    *,
    network: Network = 'mainnet',
    public: bool = False,
    validate: bool = True,
  ):
    """Build a venue from an API key, or credential-free for public data.

    Args:
      account_index: Account the API key belongs to.
      api_key_index: Slot of the API key.
      api_private_key: Private key of the API key.
      network: Lighter deployment.
      public: Skip credentials: public market data only.
      validate: Validate responses.
    """
    return cls(
      shared=Shared.new(
        account_index,
        api_key_index,
        api_private_key,
        network=network,
        public=public,
        validate=validate,
      )
    )

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """The perpetual and spot exchanges."""
    return [
      {'id': 'perp', 'type': 'perp', 'name': 'Perpetuals'},
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
    ]

  async def exchange(
    self, exchange_id: str, /
  ) -> LighterPerpExchange | LighterSpotExchange:
    """An exchange by id."""
    if exchange_id == 'spot':
      return LighterSpotExchange(shared=self.shared)
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> LighterPerpExchange:
    """The perpetual exchange."""
    if exchange_id != 'perp':
      raise ValueError(f'Unknown Lighter exchange: {exchange_id!r}')
    return LighterPerpExchange(shared=self.shared)
