"""The Margin Trade trading venue: one `perp` exchange."""

from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from ..core import Shared
from .common import Public
from .exchange import MarginTradePerpExchange


@dataclass(frozen=True, kw_only=True)
class MarginTradeMarket(Public, TradingVenue):
  """Margin Trade's perpetual markets, read for one account.

  Market ids are the venue's coin names (`'BTC'`, `'NVDA'`, `'PRL'`); the asset id is
  `'USDC'`, the collateral every market settles in.
  """

  @classmethod
  def new(
    cls,
    address: str | None = None,
    *,
    private_key: str | None = None,
    mainnet: bool = True,
    public: bool = False,
    validate: bool = True,
    account_id: str | None = None,
    rest_url: str | None = None,
    ws_url: str | None = None,
  ):
    """Build a venue reading `address` (or the key's own account).

    Account reads are public by address, so no key is needed for anything this
    implementation supports.

    Args:
      address: Account whose positions, orders, fills and funding are read.
      private_key: Ed25519 private key; only used to derive the address when none is given.
      mainnet: Use mainnet when true, testnet when false.
      public: Allow construction without a key.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
      rest_url: HTTP API root override.
      ws_url: WebSocket URL override.
    """
    return cls(
      shared=Shared.new(
        address,
        private_key=private_key,
        mainnet=mainnet,
        public=public,
        validate=validate,
        account_id=account_id,
        rest_url=rest_url,
        ws_url=ws_url,
      )
    )

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """The perpetual exchange."""
    return [
      {
        'id': 'perp',
        'type': 'perp',
        'name': 'Perpetuals',
        'url': 'https://margin.trade',
      }
    ]

  async def exchange(self, exchange_id: str, /) -> MarginTradePerpExchange:
    """An exchange by id."""
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> MarginTradePerpExchange:
    """The perpetual exchange.

    Raises:
      ValueError: The id is not `perp`.
    """
    if exchange_id != 'perp':
      raise ValueError(f'Unknown Margin Trade exchange: {exchange_id!r}')
    return MarginTradePerpExchange(shared=self.shared)
