from decimal import Decimal

from trading_sdk.market import Rules

from hyperliquid_sdk.core import (
  PRICE_MAX_DECIMALS,
  SPOT_PRICE_MAX_DECIMALS,
  MIN_ORDER_VALUE,
  MAX_RELATIVE_PRICE,
  MIN_RELATIVE_PRICE,
)

from .mixin import SpotMarketMixin


async def rules(self: SpotMarketMixin, *, refetch: bool = False) -> Rules:
  user_fees = await self.shared.load_user_fees(refetch=refetch)

  tick_decimals = min(
    PRICE_MAX_DECIMALS,
    SPOT_PRICE_MAX_DECIMALS - self.meta["base_meta"]["szDecimals"],
  )
  tick_size = Decimal(10) ** -tick_decimals

  lot_decimals = self.meta["base_meta"]["szDecimals"]
  lot_size = Decimal(10) ** -lot_decimals

  return Rules(
    base=self.base_name,
    quote=self.quote_name,
    fee_asset=self.quote_name,
    tick_size=tick_size,
    step_size=lot_size,
    min_value=MIN_ORDER_VALUE,
    rel_min_price=MIN_RELATIVE_PRICE,
    rel_max_price=MAX_RELATIVE_PRICE,
    maker_fee=Decimal(user_fees["userSpotAddRate"]),
    taker_fee=Decimal(user_fees["userSpotCrossRate"]),
    api=True,
    details={
      "user_fees": user_fees,
      "base_meta": self.meta["base_meta"],
      "quote_meta": self.meta["quote_meta"],
      "asset_meta": self.meta["asset_meta"],
    },
  )

