from decimal import Decimal

from tribulnation.sdk.market import Rules

from tribulnation.hyperliquid.core import (
  PRICE_MAX_DECIMALS,
  FUTURES_PRICE_MAX_DECIMALS,
  MIN_ORDER_VALUE,
  MAX_RELATIVE_PRICE,
  MIN_RELATIVE_PRICE,
)

from .mixin import PerpMarketMixin
from .fees import standard_perp_fees


async def rules(self: PerpMarketMixin, *, refetch: bool = False) -> Rules:
  tick_decimals = min(
    PRICE_MAX_DECIMALS,
    FUTURES_PRICE_MAX_DECIMALS - self.asset_meta['szDecimals'],
  )
  tick_size = Decimal(10) ** -tick_decimals

  lot_decimals = self.asset_meta['szDecimals']
  lot_size = Decimal(10) ** -lot_decimals

  return Rules(
    fee_asset=self.collateral_name,
    tick_size=tick_size,
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
