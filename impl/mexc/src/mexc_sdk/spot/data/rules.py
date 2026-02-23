from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Rules as _Rules

from mexc_sdk.core import SpotMixin, wrap_exceptions, MIN_ORDER_VALUE

@dataclass(frozen=True)
class Rules(SpotMixin, _Rules):
  @wrap_exceptions
  async def get(self) -> _Rules.Rules:
    return _Rules.Rules(
      base=self.info['baseAsset'],
      quote=self.info['quoteAsset'],
      fee_asset=self.info['quoteAsset'],
      tick_size=Decimal(1) / Decimal(10 ** self.info['quotePrecision']),
      step_size=Decimal(self.info['baseSizePrecision']) or Decimal('0.01'), # sometimes it just returns 0 idk
      api=self.info['isSpotTradingAllowed'],
      maker_fee=Decimal(self.info['makerCommission']),
      taker_fee=Decimal(self.info['takerCommission']),
      min_value=MIN_ORDER_VALUE, 
      details=self.info,
    )
