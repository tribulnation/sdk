"""Public spot market rules."""

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
from .fees import standard_spot_fees


@wrap_exceptions
async def rules(self: SpotMarketMixin, *, refetch: bool = False) -> Rules:
  """Instrument precision and the standard schedule, for supported quote tokens."""
  tick_decimals = min(
    PRICE_MAX_DECIMALS,
    SPOT_PRICE_MAX_DECIMALS - self.meta['base_meta']['szDecimals'],
  )
  tick_size = Decimal(10) ** -tick_decimals

  lot_decimals = self.meta['base_meta']['szDecimals']
  lot_size = Decimal(10) ** -lot_decimals

  return Rules(
    # Fees are paid in the received token: base on buys, quote on sells (ADR 0028).
    # `Trade.fee.asset` names each fill's token.
    fee_asset=None,
    tick_size=tick_size,
    step_size=lot_size,
    min_value=MIN_ORDER_VALUE,
    rel_min_price=MIN_RELATIVE_PRICE,
    rel_max_price=MAX_RELATIVE_PRICE,
    fees=await standard_spot_fees(self, refetch=refetch),
    api=True,
    details={
      'base_meta': self.meta['base_meta'],
      'quote_meta': self.meta['quote_meta'],
      'asset_meta': self.meta['asset_meta'],
    },
  )
