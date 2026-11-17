"""The Nado trading venue: a `perp` and a `spot` exchange."""

from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from ..core import Network, Shared
from .common import Public
from .exchanges import NadoPerpExchange, NadoSpotExchange


@dataclass(frozen=True, kw_only=True)
class NadoMarket(Public, TradingVenue):
  """Nado's USDT0-settled perpetuals and its spot products, on one subaccount's
  unified cross margin.

  Market ids are product symbols (`BTC-PERP`, `KBTC`); asset ids are spot symbols, and
  `USDT0` for the quote.
  """

  @classmethod
  def new(
    cls,
    *,
    network: Network = 'mainnet',
    private_key: str | None = None,
    address: str | None = None,
    subaccount: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a venue from explicit credentials; the environment is never read.

    Without a key or an address the venue is public: market data only. An address
    serves every account read (Nado's reads are public); the key also places and
    cancels orders.

    Args:
      network: Nado deployment: `mainnet` (Ink) or `testnet` (Ink Sepolia).
      private_key: Signing key: the subaccount owner's, or its linked signer's.
      address: Owner wallet of the subaccount; defaults to the key's own address.
      subaccount: Subaccount name; defaults to `default`.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    return cls(
      shared=Shared.new(
        network=network,
        private_key=private_key,
        address=address,
        subaccount=subaccount,
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

  async def exchange(self, exchange_id: str, /) -> NadoPerpExchange | NadoSpotExchange:
    """An exchange by id."""
    if exchange_id == 'spot':
      return NadoSpotExchange(shared=self.shared)
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> NadoPerpExchange:
    """The perpetual exchange.

    Raises:
      ValueError: The id is not `perp`.
    """
    if exchange_id != 'perp':
      raise ValueError(f'Unknown Nado exchange: {exchange_id!r}')
    return NadoPerpExchange(shared=self.shared)
