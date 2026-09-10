"""Market rules, from `v1/trading/market-config`."""

from typing_extensions import TYPE_CHECKING
from decimal import Decimal

from tribulnation.sdk.market import Fees, Rules

from typed_bit2me.v1.trading.markets import Entry as MarketInfo

if TYPE_CHECKING:
  from .mixin import MarketMixin


def standard_fees(base: str, quote: str) -> Fees | None:
  """Published undiscounted Pro schedules, limited to explicitly identified pairs.

  The public metadata has no stablecoin classification. Do not apply the crypto
  schedule to an unknown base that might belong to the separate stablepair tier.

  References:
    - https://support.bit2me.com/en/support/solutions/articles/35000172197
  """
  if (base, quote) in {
    ('USDC', 'EUR'),
    ('EURC', 'EUR'),
    ('EURC', 'USDC'),
    ('USDC', 'EURC'),
    ('EUR', 'USD'),
  }:
    return Fees.symmetric(maker=Decimal(0), taker=Decimal('0.0001'))
  if (base, quote) in {('BTC', 'USDC'), ('BTC', 'EUR'), ('B2M', 'EUR')}:
    return Fees.symmetric(maker=Decimal('0.005'), taker=Decimal('0.006'))
  return None


def parse_rules(info: MarketInfo) -> Rules:
  """Map one market-config row onto `Rules`.

  Public rates use the documented Pro schedule where the pair class is known.
  Missing fee metadata or an unknown pair class must not imply free trading.
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
    fee_asset=quote,
    tick_size=Decimal(str(tick_size)) if tick_size is not None else Decimal(0),
    step_size=Decimal(1).scaleb(-precision) if precision is not None else Decimal(0),
    fixed_min_qty=Decimal(str(min_amount)) if min_amount is not None else None,
    max_qty=Decimal(str(max_amount)) if max_amount is not None else None,
    fixed_min_price=Decimal(str(min_price)) if min_price is not None else None,
    fixed_max_price=Decimal(str(max_price)) if max_price is not None else None,
    fees=standard_fees(base, quote),
    api=info.get('marketEnabled') == 'enabled',
    details=info,
  )


async def rules(self: 'MarketMixin', *, refetch: bool = False) -> Rules:
  """Fetch the market rules."""
  if not refetch:
    return parse_rules(self.info)
  markets = await self.shared.load_markets(refetch=True)
  return parse_rules(markets[self.symbol])
