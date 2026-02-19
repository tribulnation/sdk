from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Rules as _Rules
from hyperliquid_sdk.core import (
  PRICE_MAX_DECIMALS, FUTURES_PRICE_MAX_DECIMALS, MIN_ORDER_VALUE,
  MAX_RELATIVE_PRICE, MIN_RELATIVE_PRICE,
)
from hyperliquid_sdk.perps.core import PerpMixin

def parse_perp_name(name: str) -> tuple[str, str]:
  if ':' in name:
    dex, name = name.split(':')
    return dex, name
  else:
    return '', name

@dataclass(frozen=True)
class Rules(PerpMixin, _Rules):
  async def get(self) -> _Rules.Rules:
    user_fees = await self.client.info.user_fees(self.address)

    tick_decimals = min(PRICE_MAX_DECIMALS, FUTURES_PRICE_MAX_DECIMALS - self.asset_meta['szDecimals'])
    tick_size = Decimal(10) ** -tick_decimals
    
    lot_decimals = self.asset_meta['szDecimals']
    lot_size = Decimal(10) ** -lot_decimals

    return _Rules.Rules(
      base=self.asset_meta['name'],
      quote=self.collateral_meta['name'],
      fee_asset=self.collateral_meta['name'],
      tick_size=tick_size,
      step_size=lot_size,
      min_value=MIN_ORDER_VALUE,
      rel_min_price=MIN_RELATIVE_PRICE,
      rel_max_price=MAX_RELATIVE_PRICE,
      maker_fee=Decimal(user_fees['userAddRate']),
      taker_fee=Decimal(user_fees['userCrossRate']),
      api=not self.asset_meta.get('isDelisted', False),
      details={
        'user_fees': user_fees,
        'collateral_meta': self.collateral_meta,
        'asset_meta': self.asset_meta,
      }
    )