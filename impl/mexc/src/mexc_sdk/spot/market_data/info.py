from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.market_data.info import Info as _Info, Information

from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class Info(MarketMixin, _Info):
  @wrap_exceptions
  async def info(self) -> Information:
    r = await self.client.spot.exchange_info(self.instrument)
    info = r[self.instrument]
    return Information(
      base=info['baseAsset'],
      quote=info['quoteAsset'],
      tick_size=Decimal(1) / Decimal(10 ** info['quotePrecision']),
      step_size=Decimal(info['baseSizePrecision']),
      api=info['isSpotTradingAllowed'],
      maker_fee=Decimal(info['makerCommission']),
      taker_fee=Decimal(info['takerCommission']),
    )
