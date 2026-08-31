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
  user_fees = await self.shared.load_user_fees(refetch=refetch)

  tick_decimals = min(
    PRICE_MAX_DECIMALS,
    SPOT_PRICE_MAX_DECIMALS - self.meta['base_meta']['szDecimals'],
  )
  tick_size = Decimal(10) ** -tick_decimals

  lot_decimals = self.meta['base_meta']['szDecimals']
  lot_size = Decimal(10) ** -lot_decimals

  return Rules(
    # Numeric token-index strings, not names — agrees with the raw form
    # report/history/assets.py already resolves to elsewhere in this package (see
    # Shared.resolve_asset_index's docstring). `base_name`/`quote_name` stay name-based
    # for their other uses (market-id formatting, matching a fill's raw `coin` field).
    base=str(self.meta['base_meta']['index']),
    quote=str(self.meta['quote_meta']['index']),
    fee_asset=str(self.meta['quote_meta']['index']),
    tick_size=tick_size,
    step_size=lot_size,
    min_value=MIN_ORDER_VALUE,
    rel_min_price=MIN_RELATIVE_PRICE,
    rel_max_price=MAX_RELATIVE_PRICE,
    maker_fee=Decimal(user_fees['userSpotAddRate']),
    taker_fee=Decimal(user_fees['userSpotCrossRate']),
    api=True,
    details={
      'user_fees': user_fees,
      'base_meta': self.meta['base_meta'],
      'quote_meta': self.meta['quote_meta'],
      'asset_meta': self.meta['asset_meta'],
    },
  )
