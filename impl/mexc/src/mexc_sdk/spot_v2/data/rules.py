from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market_v2.data import Rules as _Rules

from mexc_sdk.core import SpotMixin, wrap_exceptions

@dataclass
class Rules(SpotMixin, _Rules):
  @wrap_exceptions
  async def __call__(self) -> _Rules.Rules:
    return _Rules.Rules(
      base=self.info['baseAsset'],
      quote=self.info['quoteAsset'],
      fee_asset=self.info['quoteAsset'],
      tick_size=Decimal(1) / Decimal(10 ** self.info['quotePrecision']),
      step_size=Decimal(self.info['baseSizePrecision']),
      api=self.info['isSpotTradingAllowed'],
      maker_fee=Decimal(self.info['makerCommission']),
      taker_fee=Decimal(self.info['takerCommission']),
      details=self.info,
    )
