"""Positions, the sub-account's one cross-margin bucket, and position limits.

Extended margins at account level only: every perpetual of a sub-account shares its
balance, so every market's collateral is the same bucket.
"""

from decimal import Decimal

from typed_extended.account.balance import Balance
from typed_extended.account.schemas import Position as PositionRow
from typed_extended.info.markets import Market as MarketRow
from tribulnation.sdk.market import PerpCollateral, PerpPosition, RemainingPositionLimit


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


def leverage_cap(market: MarketRow, *, leverage: Decimal) -> Decimal:
  """The largest position value the margin schedule allows at `leverage`.

  A bracket allows leverage up to `1 / riskFactor`, up to its `upperBound` of position
  value, so the cap is the highest bound of a bracket open to users that still allows
  `leverage`, never above `maxPositionValue`. Extended validates an increasing order
  as `|position + order + triggered orders| <= max position value for the leverage`.
  """
  config = market['tradingConfig']
  bounds = [
    t['upperBound']
    for t in config['riskFactorConfig']
    if t.get('isAvailableForUsers', True) and t['riskFactor'] * leverage <= 1
  ]
  return min(max(bounds, default=Decimal(0)), config['maxPositionValue'])


def open_interest_room(market: MarketRow) -> Decimal | None:
  """What the market's open-interest limit still lets anyone open, in USD; `None`
  when unlimited (`openInterestLimit` absent or `0`).

  Both figures are USD notional: `openInterest` is `openInterestBase` (one side) at
  the mark price, and the limit was always a round USD amount (twice
  `maxPositionValue`) on mainnet, 2026-11-17. At the limit the market turns
  reduce-only.
  """
  limit = market['tradingConfig'].get('openInterestLimit')
  if limit:
    return max(limit - market['marketStats']['openInterest'], Decimal(0))


def remaining_position_limit(
  market: MarketRow, rows: list[PositionRow], *, leverage: Decimal
) -> RemainingPositionLimit:
  """The room left per direction under the leverage's position-value cap, less the
  position held in that direction (`value`, at the mark), and under the market's
  open-interest limit, which bounds both directions."""
  value = Decimal(0)
  for p in rows:
    if p['market'] == market['name']:
      value = -p['value'] if p['side'] == 'SHORT' else p['value']
  return RemainingPositionLimit.capped(
    max_notional=leverage_cap(market, leverage=leverage),
    position=value,
    remaining=open_interest_room(market),
  )
