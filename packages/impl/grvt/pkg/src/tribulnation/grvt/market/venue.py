"""The GRVT trading venue: a `perp` and a `spot` exchange."""

from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from ..core import Environment, Shared
from .common import Public
from .exchanges import GrvtPerpExchange, GrvtSpotExchange


@dataclass(frozen=True, kw_only=True)
class GrvtMarket(Public, TradingVenue):
  """GRVT's USDT-margined perpetuals and its spot instruments, on one trading
  sub-account (its futures and its spot wallet).

  Market ids are instrument names (`BTC_USDT_Perp`, `GRVT_USDT_SpotSwap`), the same on
  mainnet and testnet; asset ids are currency codes (`USDT`).
  """

  @classmethod
  def new(
    cls,
    *,
    env: Environment = 'prod',
    api_key: str | None = None,
    private_key: str | None = None,
    trading_account_id: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a venue from explicit credentials; the environment is never read.

    Without an API key the venue is public: market data only. An API key (a read-only
    one suffices) serves every account read; its private key also places orders.

    Args:
      env: GRVT deployment: `prod` (mainnet) or `testnet`.
      api_key: API key.
      private_key: The API key's EIP-712 signer key, needed only to place orders.
      trading_account_id: Trading sub-account; defaults to the one the API key is
        scoped to.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.

    Raises:
      ValueError: A private key is given without its API key.
    """
    return cls(
      shared=Shared.new(
        env=env,
        api_key=api_key,
        private_key=private_key,
        trading_account_id=trading_account_id,
        validate=validate,
        account_id=account_id,
      )
    )

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """The perpetual and spot exchanges."""
    return [
      {'id': 'perp', 'type': 'perp', 'name': 'Perpetuals'},
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
    ]

  async def exchange(self, exchange_id: str, /) -> GrvtPerpExchange | GrvtSpotExchange:
    """An exchange by id."""
    if exchange_id == 'spot':
      return GrvtSpotExchange(shared=self.shared)
    else:
      return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> GrvtPerpExchange:
    """The perpetual exchange.

    Raises:
      ValueError: The id is not `perp`.
    """
    if exchange_id != 'perp':
      raise ValueError(f'Unknown GRVT exchange: {exchange_id!r}')
    return GrvtPerpExchange(shared=self.shared)
