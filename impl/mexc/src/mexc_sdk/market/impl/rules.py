from decimal import Decimal

from trading_sdk.market import Rules

from mexc_sdk.core import MIN_ORDER_VALUE, wrap_exceptions
from .mixin import MarketMixin

@wrap_exceptions
async def rules(self: MarketMixin, *, refetch: bool = False) -> Rules:
  if refetch:
    markets = await self.shared.load_markets(refetch=True)
    info = markets[self.instrument]
  else:
    info = self.info

  # MEXC returns strings for some fields.
  quote_precision = int(info["quotePrecision"])
  base_step = Decimal(info["baseSizePrecision"])
  if base_step == 0:
    base_step = Decimal("0.01")

  return Rules(
    base=info["baseAsset"],
    quote=info["quoteAsset"],
    fee_asset=info["quoteAsset"],
    tick_size=Decimal(1) / (Decimal(10) ** quote_precision),
    step_size=base_step,
    api=bool(info["isSpotTradingAllowed"]),
    maker_fee=Decimal(info["makerCommission"]),
    taker_fee=Decimal(info["takerCommission"]),
    min_value=MIN_ORDER_VALUE,
    details=info,
  )

