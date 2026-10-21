"""The perpetual wallet's cross-margin bucket."""

from decimal import Decimal
from typed_margin_trade.schemas import ClearinghouseState
from tribulnation.sdk.market import PerpCollateral


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
