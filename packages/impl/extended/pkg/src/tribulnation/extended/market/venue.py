"""The Extended trading venue: one perpetual exchange, on one sub-account."""

from dataclasses import dataclass
from functools import cached_property

from typing_extensions import Sequence
from typed_extended.core.networks import Network
from tribulnation.sdk.market import TradingVenue

from ..core import Shared
from .common import Public
from .exchanges import ExtendedPerpExchange


@dataclass(frozen=True, kw_only=True)
class ExtendedMarket(Public, TradingVenue):
  """Extended's perpetuals, on the sub-account an API key belongs to.

  Market ids are the venue's market names (`BTC-USD`); the collateral, fee and funding
  asset is `USD`.
  """

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    stark_private_key: str | None = None,
    stark_public_key: str | None = None,
    vault: int | str | None = None,
    *,
    network: Network = 'mainnet',
    public: bool = False,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a venue for one sub-account: an API key reads and cancels, and the
    sub-account's Stark private key and vault also place orders. With `public`, market
    data only. Unset credentials fall back to `EXTENDED_*` (`EXTENDED_TESTNET_*` on
    testnet).

    Args:
      api_key: The sub-account's API key.
      stark_private_key: The sub-account's Stark private key, hex.
      stark_public_key: Its Stark public key, hex, checked against the private key.
      vault: The sub-account's vault (position id).
      network: `mainnet` or `testnet` (Starknet Sepolia).
      public: Skip credentials.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    return cls(
      shared=Shared.new(
        api_key,
        stark_private_key,
        stark_public_key,
        vault,
        network=network,
        public=public,
        validate=validate,
        account_id=account_id,
      )
    )

  @cached_property
  def perp(self) -> ExtendedPerpExchange:
    """The perpetual exchange."""
    return ExtendedPerpExchange(shared=self.shared)

  async def exchanges(self) -> Sequence[TradingVenue.ExchangeDescription]:
    """The perpetual exchange."""
    return [{'id': 'perp', 'type': 'perp', 'name': 'Perpetuals'}]

  async def exchange(self, exchange_id: str, /) -> ExtendedPerpExchange:
    """An exchange by id: only `perp`."""
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> ExtendedPerpExchange:
    """The perpetual exchange."""
    if exchange_id != 'perp':
      raise ValueError(f'Unknown Extended exchange: {exchange_id!r}')
    return self.perp
