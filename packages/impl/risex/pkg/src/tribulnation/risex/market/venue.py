"""The RISEx trading venue: one perpetual exchange, on one account."""

from dataclasses import dataclass
from functools import cached_property

from typing_extensions import Sequence
from typed_risex.core.networks import Network
from tribulnation.sdk.market import TradingVenue

from ..core import Shared
from .common import Public
from .exchanges import RisexPerpExchange


@dataclass(frozen=True, kw_only=True)
class RisexMarket(Public, TradingVenue):
  """RISEx's USDC-margined perpetuals, on one account.

  Market ids are the venue's numeric `market_id` (`'1'` is BTC/USDC); the collateral,
  fee and funding asset is USDC.
  """

  @classmethod
  def new(
    cls,
    *,
    network: Network = 'mainnet',
    account_key: str | None = None,
    signer_key: str | None = None,
    address: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a venue for one account; the environment is never read.

    A registered signer key trades (with the account's `address`, or the account key);
    either key also logs in for `fees`. An address alone serves every other account
    read, since RISEx's account reads are public. Neither: market data only.

    Args:
      network: `mainnet` or `testnet`.
      account_key: The account wallet's private key, hex.
      signer_key: A registered signer's private key, hex.
      address: The account's address.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    return cls(
      shared=Shared.new(
        network=network,
        account_key=account_key,
        signer_key=signer_key,
        address=address,
        validate=validate,
        account_id=account_id,
      )
    )

  @cached_property
  def perp(self) -> RisexPerpExchange:
    """The perpetual exchange."""
    return RisexPerpExchange(shared=self.shared)

  async def exchanges(self) -> Sequence[TradingVenue.ExchangeDescription]:
    """The perpetual exchange."""
    return [{'id': 'perp', 'type': 'perp', 'name': 'Perpetuals'}]

  async def exchange(self, exchange_id: str, /) -> RisexPerpExchange:
    """An exchange by id: only `perp`."""
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> RisexPerpExchange:
    """The perpetual exchange."""
    if exchange_id != 'perp':
      raise ValueError(f'Unknown RISEx exchange: {exchange_id!r}')
    return self.perp
