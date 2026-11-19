"""The EVEDEX trading venue: one perpetual exchange, on one account."""

from dataclasses import dataclass
from functools import cached_property

from typing_extensions import Sequence
from tribulnation.sdk.market import TradingVenue

from ..core import Shared
from .common import Public
from .exchanges import EvedexPerpExchange


@dataclass(frozen=True, kw_only=True)
class EvedexMarket(Public, TradingVenue):
  """EVEDEX's USDT-margined perpetuals, on one account.

  Market ids are instrument names (`BTCUSD`); the collateral, fee and funding coin is
  USDT (`usdt`).
  """

  @classmethod
  def new(
    cls,
    *,
    private_key: str | None = None,
    api_key: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a venue for one account.

    The wallet's private key reads and trades; an API key alone serves every REST
    account read. Neither: market data only. `typed-evedex` fills an unset key from
    `EVEDEX_PRIVATE_KEY`/`EVEDEX_API_KEY` when the other one is given.

    Args:
      private_key: The wallet's private key, hex.
      api_key: An API key.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    return cls(
      shared=Shared.new(
        private_key=private_key,
        api_key=api_key,
        validate=validate,
        account_id=account_id,
      )
    )

  @cached_property
  def perp(self) -> EvedexPerpExchange:
    """The perpetual exchange."""
    return EvedexPerpExchange(shared=self.shared)

  async def exchanges(self) -> Sequence[TradingVenue.ExchangeDescription]:
    """The perpetual exchange."""
    return [{'id': 'perp', 'type': 'perp', 'name': 'Perpetuals'}]

  async def exchange(self, exchange_id: str, /) -> EvedexPerpExchange:
    """An exchange by id: only `perp`."""
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> EvedexPerpExchange:
    """The perpetual exchange."""
    if exchange_id != 'perp':
      raise ValueError(f'Unknown EVEDEX exchange: {exchange_id!r}')
    return self.perp
