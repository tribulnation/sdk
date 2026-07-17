from decimal import Decimal

from hyperliquid.info.perps.clearinghouse_state import (
  ClearinghouseStateResponse,
  Position,
  LeverageIsolated,
)

from tribulnation.sdk.market import Collateral, PerpCollateral

from tribulnation.hyperliquid.core import wrap_exceptions
from .mixin import PerpMixin, PerpMarketMixin, SpotMarketMixin


def cross_collateral(state: ClearinghouseStateResponse) -> PerpCollateral:
  """The account-wide CROSS margin bucket.

  Every field comes straight from the venue: `crossMarginSummary.accountValue`
  is the cross equity, `crossMaintenanceMarginUsed` is the exact maintenance
  margin the venue enforces, and `withdrawable` is the free collateral.
  """
  summary = state['crossMarginSummary']
  equity = Decimal(summary['accountValue'])
  ntl = Decimal(summary['totalNtlPos'])
  # leverage = total position notional / equity; 0 when flat or non-positive equity.
  leverage = ntl / equity if equity > 0 else Decimal(0)
  free_collateral = Decimal(state['withdrawable'])
  return PerpCollateral(
    equity=equity,
    free_collateral=free_collateral,
    initial_margin=equity - free_collateral,
    maintenance_margin=Decimal(state['crossMaintenanceMarginUsed']),
    leverage=leverage,
    margin_mode='cross',
  )


def isolated_collateral(pos: Position, leverage: LeverageIsolated) -> PerpCollateral:
  """The per-market ISOLATED margin bucket for a single position.

  HL exposes no per-position maintenance-margin field, so we reconstruct it
  from the venue's documented margining rule: the maintenance margin fraction
  is `1 / (2 * maxLeverage)`, i.e. half the initial margin fraction at max
  leverage. Hence `maintenance_margin = positionValue / (2 * maxLeverage)`.
  This keeps `maintenance_ratio = maintenance_margin / equity` honest and
  consistent with the venue's `liquidationPx` (which is derived from the same
  rule). We prefer this over back-solving from `liquidationPx` because
  `liquidationPx` can be null (e.g. tiny/flat residuals) whereas
  `positionValue` and `maxLeverage` are always present.

  `equity = rawUsd + unrealizedPnl`: the isolated margin locked in the bucket
  (`leverage.rawUsd`) plus the position's unrealized PnL. `free_collateral` is
  the excess of equity over the margin actually in use (`marginUsed`), floored
  at 0 so it never goes negative near liquidation.
  """
  raw_usd = Decimal(leverage['rawUsd'])
  upnl = Decimal(pos['unrealizedPnl'])
  equity = raw_usd + upnl
  margin_used = Decimal(pos['marginUsed'])
  free_collateral = max(equity - margin_used, Decimal(0))
  position_value = Decimal(pos['positionValue'])
  max_leverage = Decimal(pos['maxLeverage'])
  maintenance_margin = (
    position_value / (2 * max_leverage) if max_leverage > 0 else Decimal(0)
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=free_collateral,
    initial_margin=margin_used,
    maintenance_margin=maintenance_margin,
    leverage=Decimal(leverage['value']),
    margin_mode='isolated',
  )


@wrap_exceptions
async def perp_exchange_collateral(self: PerpMixin) -> PerpCollateral:
  """Exchange-level bucket = the account CROSS pool (one bucket per exchange)."""
  state = await self.client.info.clearinghouse_state(self.address, dex=self.dex_name)
  return cross_collateral(state)


@wrap_exceptions
async def perp_market_collateral(self: PerpMarketMixin) -> PerpCollateral:
  """Mode-aware bucket for a single perp market.

  Cross positions (and no position) share the account cross pool; isolated
  positions get their own bucket.
  """
  state = await self.client.info.clearinghouse_state(self.address, dex=self.dex_name)
  for entry in state['assetPositions']:
    pos = entry['position']
    if pos['coin'] == self.asset_name:
      leverage = pos['leverage']
      if leverage['type'] == 'isolated':
        return isolated_collateral(pos, leverage)
      break  # cross position → fall through to the cross pool
  return cross_collateral(state)


@wrap_exceptions
async def spot_market_collateral(self: SpotMarketMixin) -> Collateral:
  """Spot bucket = the quote/collateral token balance.

  `equity = total` balance of the quote token; `free_collateral = total - hold`
  (the portion not locked by resting orders).
  """
  state = await self.client.info.spot_clearinghouse_state(self.address)
  for balance in state['balances']:
    if balance['token'] == self.quote_meta['index']:
      total = Decimal(balance['total'])
      hold = Decimal(balance['hold'])
      return Collateral(equity=total, free_collateral=total - hold)
  return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
