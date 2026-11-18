"""Spot balances, read off the account-wide extended balance list (`BalanceEx`)."""

from typing_extensions import TYPE_CHECKING, Mapping
from datetime import timedelta
from decimal import Decimal

from tribulnation.sdk.market import Balance, SpotBalances

from typed_kraken.spot.account.balance_ex import ExtendedBalance

if TYPE_CHECKING:
  from .mixin import MarketMixin, Shared


def parse_balance(entry: ExtendedBalance | None) -> Balance:
  """One asset's balance: `total` is `balance`, `free` what resting orders do not hold.

  `hold_trade` is what open spot orders reserve. Credit lines (`credit`,
  `credit_used`) are an institutional facility and are not counted as free. An asset
  the account never held is absent from `BalanceEx`, and is zero.

  Args:
    entry: The asset's `BalanceEx` row, or `None` when absent.
  """
  if entry is None:
    return Balance(total=Decimal(0), free=Decimal(0))
  else:
    total = entry.get('balance', Decimal(0))
    return Balance(total=total, free=total - entry.get('hold_trade', Decimal(0)))


async def asset_balance(
  shared: 'Shared', asset: str, *, ttl: timedelta | None
) -> Balance:
  """One spot asset's balance by internal id (`ZUSD`, `KAVA`).

  Raises:
    ValueError: No listed pair trades the asset, so it is no Spot asset ID.
  """
  pairs = await shared.load_pairs()
  if not any(
    asset in (p['info'].get('base'), p['info'].get('quote')) for p in pairs.values()
  ):
    raise ValueError(f'Unknown Kraken Spot asset: {asset}')
  balances: Mapping[str, ExtendedBalance] = await shared.load_balances(ttl=ttl)
  return parse_balance(balances.get(asset))


async def balances(self: 'MarketMixin', *, ttl: timedelta | None) -> SpotBalances:
  """The market's base and quote balances, from one `BalanceEx` answer."""
  rows = await self.shared.load_balances(ttl=ttl)
  return SpotBalances(
    base=parse_balance(rows.get(self.base)), quote=parse_balance(rows.get(self.quote))
  )
