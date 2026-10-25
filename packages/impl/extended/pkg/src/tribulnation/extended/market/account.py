"""Positions and the sub-account's one cross-margin bucket.

Extended margins at account level only: every perpetual of a sub-account shares its
balance, so every market's collateral is the same bucket.
"""

from decimal import Decimal

from typed_extended.account.balance import Balance
from typed_extended.account.schemas import Position as PositionRow
from tribulnation.sdk.market import PerpCollateral, PerpPosition


def bucket(balance: Balance | None) -> PerpCollateral:
  """The sub-account's cross bucket; `None` is the venue's zero balance.

  Equity is `balance + spot equity + unrealised PnL`, free collateral
  `availableForTrade` (equity less the margin perps and spot buy orders reserve). The
  venue publishes no maintenance-margin figure, only `marginRatio`, documented as the
  sum of maintenance requirements over equity, so the requirement is
  `marginRatio x equity`. Leverage is the venue's `exposure / equity`.
  """
  if balance is None:
    zero = Decimal(0)
    return PerpCollateral(
      equity=zero,
      free_collateral=zero,
      initial_margin=zero,
      maintenance_margin=zero,
      leverage=zero,
      margin_mode='cross',
    )
  return PerpCollateral(
    equity=balance['equity'],
    free_collateral=balance['availableForTrade'],
    initial_margin=balance['initialMargin'],
    maintenance_margin=balance['marginRatio'] * balance['equity'],
    leverage=balance['leverage'],
    margin_mode='cross',
  )


def perp_position(rows: list[PositionRow], market: str) -> PerpPosition:
  """The signed position and entry price; no row is flat (`size` is unsigned beside
  `side`)."""
  for p in rows:
    if p['market'] == market:
      sign = -1 if p['side'] == 'SHORT' else 1
      return PerpPosition(size=p['size'] * sign, entry_price=p['openPrice'])
  return PerpPosition()
