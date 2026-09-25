"""Positions, collateral buckets and available notional from the account endpoint.

Perpetual figures read the same fields in classic and unified accounts. Spot collateral
depends on the mode, and only unified accounts are supported, as for Hyperliquid.
"""

from decimal import Decimal

from typed_lighter.api.account.get import DetailedAccount
from typed_lighter.api.markets.order_book_details import PerpsOrderBookDetail
from typed_lighter.schemas import AccountAsset, AccountPosition
from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import Collateral, PerpCollateral, PerpPosition, Position

from ..core import percent

CROSS, ISOLATED = 0, 1
"""Position margin modes."""
UNIFIED = 1
"""`account_trading_mode` of a unified account (USDC shared by spot and perps)."""


def position_of(acct: DetailedAccount, market_id: int) -> AccountPosition | None:
  """The account's entry for a market; absent when it never traded it."""
  return next((p for p in acct['positions'] if p['market_id'] == market_id), None)


def perp_position(acct: DetailedAccount, market_id: int) -> PerpPosition:
  """The signed position and average entry (`position` is unsigned beside `sign`)."""
  p = position_of(acct, market_id)
  if p is None:
    return PerpPosition()
  return PerpPosition(size=p['position'] * p['sign'], entry_price=p['avg_entry_price'])


def cross_free(acct: DetailedAccount) -> Decimal:
  """Cross equity above its initial requirement (the venue's `user_stats` cross
  `available_balance`). The account's own `available_balance` is not the cross figure:
  it adds every isolated position's free margin."""
  return acct['cross_asset_value'] - acct['cross_initial_margin_requirement']


def cross_bucket(acct: DetailedAccount) -> PerpCollateral:
  """The cross-margin bucket, from the account's cross figures."""
  equity = acct['cross_asset_value']
  notional = sum(
    (abs(p['position_value']) for p in acct['positions'] if p['margin_mode'] == CROSS),
    Decimal(0),
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=cross_free(acct),
    initial_margin=acct['cross_initial_margin_requirement'],
    maintenance_margin=acct['cross_maintenance_margin_requirement'],
    leverage=notional / equity if equity > 0 else Decimal(0),
    margin_mode='cross',
  )


def isolated_bucket(p: AccountPosition, detail: PerpsOrderBookDetail) -> PerpCollateral:
  """One isolated position's bucket. The account reports its parts, not its totals:
  equity is `allocated_margin + unrealized_pnl`, and the requirements are the position
  value times the position's initial and the market's maintenance margin fractions.
  Checked live: the equity matches `user_stats`, the maintenance requirement reproduces
  `liquidation_price`, and margin removals are accepted up to the free figure."""
  notional = abs(p['position_value'])
  equity = p['allocated_margin'] + p['unrealized_pnl']
  initial = notional * percent(p['initial_margin_fraction'])
  return PerpCollateral(
    equity=equity,
    free_collateral=max(equity - initial, Decimal(0)),
    initial_margin=initial,
    maintenance_margin=notional * detail['maintenance_margin_fraction'] / 10_000,
    leverage=notional / equity if equity > 0 else Decimal(0),
    margin_mode='isolated',
  )


def market_bucket(
  acct: DetailedAccount, market_id: int, detail: PerpsOrderBookDetail
) -> PerpCollateral:
  """The bucket backing a market: its isolated position's, else cross."""
  p = position_of(acct, market_id)
  if p is not None and p['margin_mode'] == ISOLATED:
    return isolated_bucket(p, detail)
  return cross_bucket(acct)


def perp_available_notional(
  acct: DetailedAccount, market_id: int, detail: PerpsOrderBookDetail
) -> Decimal:
  """Free cross collateral times the market's configured leverage (`100 /
  initial_margin_fraction`), or the venue default for a market never configured.
  Isolated positions are funded from cross collateral too."""
  p = position_of(acct, market_id)
  fraction = (
    percent(p['initial_margin_fraction'])
    if p is not None
    else Decimal(detail['default_initial_margin_fraction']) / 10_000
  )
  return cross_free(acct) / fraction


def balance_of(acct: DetailedAccount, asset_id: int) -> AccountAsset | None:
  """The account's balance row of one asset, if it holds any."""
  return next((a for a in acct['assets'] if a['asset_id'] == asset_id), None)


def spot_position(acct: DetailedAccount, base_asset_id: int) -> Position:
  """The base asset's balance, locked part included."""
  row = balance_of(acct, base_asset_id)
  return Position(size=row['balance'] if row else Decimal(0))


def spot_collateral(acct: DetailedAccount, quote_asset_id: int) -> Collateral:
  """The quote asset's spot collateral on a unified account.

  A margin-enabled quote asset (USDC) lives in `margin_balance`, shared with perps. Resting
  bids lock `locked_balance`, which `available_balance` does not reflect, so a spot bid can
  spend `available_balance - locked_balance`. Any other quote asset is its spot balance.

  Raises:
    ApiError: The account is in classic mode, which is unsupported.
  """
  if acct['account_trading_mode'] != UNIFIED:
    raise ApiError('Only unified Lighter accounts are supported for spot collateral')
  row = balance_of(acct, quote_asset_id)
  if row is None:
    return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
  if row['margin_mode'] == 'enabled':
    return Collateral(
      equity=row['margin_balance'],
      free_collateral=max(
        acct['available_balance'] - row['locked_balance'], Decimal(0)
      ),
    )
  return Collateral(
    equity=row['balance'], free_collateral=row['balance'] - row['locked_balance']
  )
