from dataclasses import dataclass

from tribulnation.sdk import TradingVenue

from .impl import ExchangeMixin
from .exchange import Exchange

# MIGRATION NOTE: the old `<BASE>-USD:<N>` market-suffix `parse_market_id` has been
# retired here too. The subaccount is now selected via the exchange id: `perp` (parent)
# or `perp.<N>` (child). The `.`-qualifier keeps the top-level `<account>:<exchange>:<market>`
# colon split (core `markets.py`) unaffected.

@dataclass(frozen=True)
class DydxMarket(ExchangeMixin, TradingVenue):

  @property
  def venue_id(self) -> str:
    return 'dydx'

  async def exchange(self, exchange_id: str, /) -> Exchange:
    """Resolve a perpetual exchange (margin bucket) by id.

    - `perp`: the account's parent subaccount (the default cross pool).
    - `perp.<N>`: subaccount `<N>`, validated `N % 128 == parent_subaccount` (child
      subaccounts of parent `p` are `p, 128+p, 256+p, ...`).
    """
    parent = self.shared.parent_subaccount
    if exchange_id == 'perp':
      return Exchange(shared=self.shared, subaccount=parent)
    if exchange_id.startswith('perp.'):
      suffix = exchange_id[len('perp.'):]
      try:
        subaccount = int(suffix)
      except ValueError:
        raise ValueError(
          f'Invalid exchange ID: {exchange_id!r}. Expected "perp" or "perp.<N>" with integer <N>.'
        )
      if subaccount % 128 != parent:
        raise ValueError(
          f'Invalid subaccount {subaccount} for exchange {exchange_id!r}: child subaccounts of '
          f'parent {parent} must satisfy N % 128 == {parent} '
          f'(i.e. {parent}, {128 + parent}, {256 + parent}, ...).'
        )
      return Exchange(shared=self.shared, subaccount=subaccount)
    raise ValueError(f'Invalid exchange ID: {exchange_id!r}. Only "perp" or "perp.<N>" are supported.')

  async def perp_exchange(self, exchange_id: str, /):
    return await self.exchange(exchange_id)

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    return [{'id': 'perp', 'type': 'perp'}]
