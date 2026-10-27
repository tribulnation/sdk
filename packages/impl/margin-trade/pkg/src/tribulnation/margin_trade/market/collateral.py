"""The perpetual wallet's cross-margin bucket, and spot wallet balances."""

from decimal import Decimal
from typed_margin_trade.info.spot_clearinghouse_state import SpotClearinghouseState
from typed_margin_trade.schemas import ClearinghouseState
from tribulnation.sdk.market import Balance, PerpCollateral


def spot_balance(state: SpotClearinghouseState, token: int) -> Balance:
  """One spot token's balance, zero when the account holds none; free is what resting
  orders do not hold.

  Args:
    state: The account's `spotClearinghouseState`.
    token: The token index.
  """
  for row in state['balances']:
    if row['token'] == token:
      return Balance(total=row['total'], free=row['total'] - row['hold'])
  return Balance(total=Decimal(0), free=Decimal(0))


def cross_collateral(state: ClearinghouseState) -> PerpCollateral:
  """
  The cross bucket of the perpetual wallet, which is its own account (spot is separate).

  Equity is `crossMarginSummary.accountValue` (unrealized PnL included), initial margin
  its `totalMarginUsed`, maintenance `crossMaintenanceMarginUsed`, free collateral the
  venue's `withdrawable`, and leverage `totalNtlPos / accountValue`.

  Args:
    state: The account's `clearinghouseState`.
  """
  summary = state['crossMarginSummary']
  equity = summary['accountValue']
  return PerpCollateral(
    equity=equity,
    free_collateral=state['withdrawable'],
    initial_margin=summary['totalMarginUsed'],
    maintenance_margin=state['crossMaintenanceMarginUsed'],
    leverage=summary['totalNtlPos'] / equity if equity > 0 else Decimal(0),
    margin_mode='cross',
  )
