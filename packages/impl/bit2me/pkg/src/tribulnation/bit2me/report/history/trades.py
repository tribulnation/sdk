"""Spot trades, from `v1/trading/trade`."""

from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import Fee, SpotTrade
from tribulnation.bit2me.core import Mixin

from typed_bit2me.schemas import TradeResponse

TRADES_PAGE = 50
"""Rows per page. `v1/trading/trade` caps a page at 50."""


def parse_trade(row: TradeResponse) -> SpotTrade:
  """Map one Trading Spot trade onto a `SpotTrade` observation."""
  symbol = row.get('symbol')
  base, _, quote = symbol.partition('/') if symbol else ('', '', '')
  amount = Decimal(str(row.get('amount', 0)))
  price = row.get('price')
  fee_amount = row.get('feeAmount')
  fee_asset = row.get('feeCurrency')
  return SpotTrade(
    id=row.get('id'),
    time=row.get('createdAt'),
    base=base or None,
    quote=quote or None,
    pair=symbol,
    size=amount if row.get('side') == 'buy' else -amount,
    price=Decimal(str(price)) if price is not None else None,
    order_id=row.get('orderId'),
    fee=Fee(amount=Decimal(str(fee_amount)), asset=fee_asset)
    if fee_amount and fee_asset
    else None,
  )


@dataclass(frozen=True, kw_only=True)
class SpotTrades(Mixin):
  """The account's Trading Spot fills, across every market."""

  @SDK.method
  async def spot_trades(self, start: datetime, end: datetime) -> Sequence[SpotTrade]:
    """Fetch every Trading Spot fill in a window.

    Unfiltered by symbol: `v1/trading/trade` accepts `startTime`/`endTime` and
    reports its own `total`, so one offset walk covers all markets at once.

    Args:
      start: Start of the window (inclusive).
      end: End of the window (inclusive).
    """
    out: list[SpotTrade] = []
    offset = 0
    while True:
      current = offset
      page = await self.call_bit2me(
        lambda: self.client.v1.trading.trades.list(
          start_time=start, end_time=end, limit=TRADES_PAGE, offset=current
        )
      )
      rows = page.get('data', [])
      out.extend(parse_trade(row) for row in rows)
      offset += len(rows)
      if not rows or offset >= int(page.get('total') or 0):
        return out
