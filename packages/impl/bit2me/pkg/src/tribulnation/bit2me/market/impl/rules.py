"""Market rules, from `v1/trading/market-config`."""

from typing_extensions import TYPE_CHECKING
from decimal import Decimal

from tribulnation.sdk.market import Rules

from typed_bit2me.v1.trading.markets import Entry as MarketInfo

if TYPE_CHECKING:
  from .mixin import MarketMixin


def parse_rules(info: MarketInfo) -> Rules:
  """Map one market-config row onto `Rules`.

  `maker_fee`/`taker_fee` are always `0`, and that is a gap rather than a claim that
  trading is free: `typed_bit2me` has no fee-schedule endpoint and no market-config
  field carries a rate. Bit2Me only ever reports a fee after the fact, per fill
  (`feeAmount`/`feeCurrency` on a trade), never as a rate quotable in advance.
  """
  symbol = info.get('symbol') or ''
  base, _, quote = symbol.partition('/')
  precision = info.get('amountPrecision')
  tick_size = info.get('tickSize')
  min_amount = info.get('minAmount')
  max_amount = info.get('maxAmount')
  min_price = info.get('minPrice')
  max_price = info.get('maxPrice')
  return Rules(
    base=base,
    quote=quote,
    fee_asset=quote,
    tick_size=Decimal(str(tick_size)) if tick_size is not None else Decimal(0),
    step_size=Decimal(1).scaleb(-int(precision))
    if precision is not None
    else Decimal(0),
    fixed_min_qty=Decimal(str(min_amount)) if min_amount is not None else None,
    max_qty=Decimal(str(max_amount)) if max_amount is not None else None,
    fixed_min_price=Decimal(str(min_price)) if min_price is not None else None,
    fixed_max_price=Decimal(str(max_price)) if max_price is not None else None,
    maker_fee=Decimal(0),
    taker_fee=Decimal(0),
    api=info.get('marketEnabled') == 'enabled',
    details=info,
  )


async def rules(self: 'MarketMixin', *, refetch: bool = False) -> Rules:
  """Fetch the market rules."""
  if not refetch:
    return parse_rules(self.info)
  markets = await self.shared.load_markets(refetch=True)
  return parse_rules(markets[self.symbol])
