from decimal import Decimal

from tribulnation.sdk.market import Rules

from tribulnation.hyperliquid.core import (
  PRICE_MAX_DECIMALS,
  SPOT_PRICE_MAX_DECIMALS,
  MIN_ORDER_VALUE,
  MAX_RELATIVE_PRICE,
  MIN_RELATIVE_PRICE,
  wrap_exceptions,
)

from .mixin import SpotMarketMixin


@wrap_exceptions
async def rules(self: SpotMarketMixin, *, refetch: bool = False) -> Rules:
  tick_decimals = min(
    PRICE_MAX_DECIMALS,
    SPOT_PRICE_MAX_DECIMALS - self.meta['base_meta']['szDecimals'],
  )
  tick_size = Decimal(10) ** -tick_decimals

  lot_decimals = self.meta['base_meta']['szDecimals']
  lot_size = Decimal(10) ** -lot_decimals

  return Rules(
    # Actual fee tokens use the same numeric index as wallet/report balances.
    fee_asset=str(self.meta['quote_meta']['index']),
    tick_size=tick_size,
    step_size=lot_size,
    min_value=MIN_ORDER_VALUE,
    rel_min_price=MIN_RELATIVE_PRICE,
    rel_max_price=MAX_RELATIVE_PRICE,
    fees=None,
    api=True,
    details={
      'base_meta': self.meta['base_meta'],
      'quote_meta': self.meta['quote_meta'],
      'asset_meta': self.meta['asset_meta'],
    },
  )
