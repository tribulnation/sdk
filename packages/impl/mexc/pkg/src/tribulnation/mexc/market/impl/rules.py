from decimal import Decimal

from tribulnation.sdk.market import Rules

from tribulnation.mexc.core import MIN_ORDER_VALUE, wrap_exceptions
from .mixin import MarketMixin

@wrap_exceptions
async def rules(self: MarketMixin, *, refetch: bool = False) -> Rules:
  if refetch:
    markets = await self.shared.load_markets(refetch=True)
    info = markets[self.instrument]
  else:
    info = self.info

  # MEXC returns strings for some fields.
  quote_precision = int(info.get('quotePrecision') or 8)
  base_step = Decimal(str(info.get('baseSizePrecision') or '0.01'))
  if base_step == 0:
    base_step = Decimal('0.01')

  rel_min_price: Decimal | None = None
  rel_max_price: Decimal | None = None

  for filter in info.get('filters', []):
    if filter.get('filterType') == 'PERCENT_PRICE_BY_SIDE':
      new_min_price = Decimal(1) - Decimal(str(filter.get('askMultiplierDown') or '0'))
      rel_min_price = max(rel_min_price or Decimal('-inf'), new_min_price)
      
      new_max_price = Decimal(1) + Decimal(str(filter.get('bidMultiplierUp') or '0'))
      rel_max_price = min(rel_max_price or Decimal('inf'), new_max_price)

  return Rules(
    base=info.get('baseAsset') or '',
    quote=info.get('quoteAsset') or '',
    fee_asset=info.get('quoteAsset') or '',
    tick_size=Decimal(1) / (Decimal(10) ** quote_precision),
    step_size=base_step,
    api=bool(info.get('isSpotTradingAllowed', True)),
    maker_fee=Decimal(str(info.get('makerCommission') or '0')),
    taker_fee=Decimal(str(info.get('takerCommission') or '0')),
    min_value=MIN_ORDER_VALUE,
    rel_min_price=rel_min_price,
    rel_max_price=rel_max_price,
    details=info,
  )
