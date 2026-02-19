from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Rules as _Rules
from hyperliquid_sdk.core import (
  PRICE_MAX_DECIMALS, SPOT_PRICE_MAX_DECIMALS, MIN_ORDER_VALUE,
  MAX_RELATIVE_PRICE, MIN_RELATIVE_PRICE,
)
from hyperliquid_sdk.spot.core import SpotMixin

@dataclass(frozen=True)
class Rules(SpotMixin, _Rules):
  async def get(self) -> _Rules.Rules:
    user_fees = await self.client.info.user_fees(self.address)

    tick_decimals = min(PRICE_MAX_DECIMALS, SPOT_PRICE_MAX_DECIMALS - self.base_meta['szDecimals'])
    tick_size = Decimal(10) ** -tick_decimals
    
    lot_decimals = self.base_meta['szDecimals']
    lot_size = Decimal(10) ** -lot_decimals

    return _Rules.Rules(
      base=self.base_meta['name'],
      quote=self.quote_meta['name'],
      fee_asset=self.quote_meta['name'],
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
        'base_meta': self.base_meta,
        'quote_meta': self.quote_meta,
        'asset_meta': self.asset_meta,
      }
    )