"""Positions, collateral and leverage from `clearinghouseState` and `activeAssetData`."""

from decimal import Decimal

from typed_margintrade.schemas import AssetPosition, ClearinghouseState
from tribulnation.sdk.market import PerpCollateral, PerpPosition


def position_of(state: ClearinghouseState, coin: str) -> AssetPosition | None:
  """The account's open position on `coin`, if any."""
  for entry in state['assetPositions'] or []:
    if entry['position']['coin'] == coin:
      return entry


def perp_position(state: ClearinghouseState, coin: str) -> PerpPosition:
  """The signed size and average entry; flat when there is no position."""
  if (entry := position_of(state, coin)) is not None:
    return PerpPosition(
      size=entry['position']['szi'], entry_price=entry['position']['entryPx']
    )
  else:
    return PerpPosition()


def cross_collateral(state: ClearinghouseState) -> PerpCollateral:
  """The cross-margin bucket: account value, withdrawable USDC, margin in use and the
  venue's cross maintenance margin."""
  summary = state['crossMarginSummary']
  equity = summary['accountValue']
  ntl = summary['totalNtlPos']
  return PerpCollateral(
    equity=equity,
    free_collateral=state['withdrawable'],
    initial_margin=summary['totalMarginUsed'],
    maintenance_margin=state['crossMaintenanceMarginUsed'],
    leverage=ntl / equity if equity > 0 else Decimal(0),
    margin_mode='cross',
  )


def market_collateral(state: ClearinghouseState, coin: str) -> PerpCollateral:
  """The bucket backing `coin`: its isolated margin when the position is isolated, else
  cross. An isolated bucket's maintenance margin is not reported by the venue; it is the
  documented per-position rule, `notional / (2 * maxLeverage)` (docs.margin.trade, Margin:
  Maintenance Margin)."""
  entry = position_of(state, coin)
  if entry is not None and entry['position']['leverage']['type'] == 'isolated':
    pos = entry['position']
    raw = pos['leverage'].get('rawUsd', Decimal(0))
    equity = raw + pos['unrealizedPnl']
    max_leverage = Decimal(pos['maxLeverage'])
    return PerpCollateral(
      equity=equity,
      free_collateral=max(equity - pos['marginUsed'], Decimal(0)),
      initial_margin=pos['marginUsed'],
      maintenance_margin=pos['positionValue'] / (2 * max_leverage)
      if max_leverage > 0
      else Decimal(0),
      leverage=Decimal(pos['leverage']['value']),
      margin_mode='isolated',
    )
  else:
    return cross_collateral(state)
