"""Public perpetual market rules."""

from decimal import Decimal

from tribulnation.sdk.market import Rules

from tribulnation.hyperliquid.core import (
  MAX_SIGNIFICANT_FIGURES,
  MIN_ORDER_VALUE,
  MAX_RELATIVE_PRICE,
  MIN_RELATIVE_PRICE,
)

from .mixin import PerpMarketMixin
from .fees import standard_perp_fees


async def rules(self: PerpMarketMixin, *, refetch: bool = False) -> Rules:
  """Instrument precision and the standard schedule; fees and funding settle in collateral."""
  lot_decimals = self.asset_meta['szDecimals']
  lot_size = Decimal(10) ** -lot_decimals

  return Rules(
    # Same numeric token index as wallet/report balances and `Trade.fee.asset`.
    fee_asset=str(self.collateral_meta['index']),
    tick_size=self.tick_size,
    sig_figs=MAX_SIGNIFICANT_FIGURES,
    step_size=lot_size,
    min_value=MIN_ORDER_VALUE,
    rel_min_price=MIN_RELATIVE_PRICE,
    rel_max_price=MAX_RELATIVE_PRICE,
    fees=await standard_perp_fees(self, refetch=refetch),
    api=not self.asset_meta.get('isDelisted', False),
    details={
      'collateral_meta': self.collateral_meta,
      'asset_meta': self.asset_meta,
    },
  )
