"""Own-trade history and stream."""

from typing_extensions import TYPE_CHECKING, AsyncIterable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.market import Trade

from typed_bit2me.schemas import TradeResponse
from typed_bit2me.trading_ws.my_trades import MyTradeUpdate

if TYPE_CHECKING:
  from .mixin import MarketMixin

TRADES_PAGE = 50
"""Trades per page. `v1/trading/trade` caps a page at 50."""


def parse_trade(row: TradeResponse) -> Trade:
  """Map one Bit2Me fill onto a `Trade`."""
  qty = Decimal(str(row.get('amount', 0)))
  price = row.get('price')
  fee_amount = row.get('feeAmount')
  fee_asset = row.get('feeCurrency')
  return Trade(
    id=row.get('id'),
    price=Decimal(str(price)) if price is not None else Decimal(0),
    qty=qty if row.get('side') == 'buy' else -qty,
    time=row.get('createdAt') or datetime.now(timezone.utc),
    maker=bool(row.get('isMaker')),
    fee=Trade.Fee(amount=Decimal(str(fee_amount)), asset=fee_asset)
    if fee_amount and fee_asset
    else None,
    details=row,
  )


def parse_update(update: MyTradeUpdate) -> Trade:
  """Map one streamed fill onto a `Trade`."""
  qty = Decimal(str(update['amount']))
  fee = update.get('fee')
  return Trade(
    id=update['id'],
    price=Decimal(str(update['price'])),
    qty=qty if update['side'] == 'buy' else -qty,
    time=update.get('datetime') or datetime.now(timezone.utc),
    maker=bool(update.get('isMaker')),
    fee=Trade.Fee(amount=Decimal(str(fee['cost'])), asset=fee['currency'])
    if fee
    else None,
    details=update,
  )


async def trades_history(
  self: 'MarketMixin', start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Fetch the market's own-trade history, one page at a time."""
  offset = 0
  while True:
    current = offset
    page = await self.call_bit2me(
      lambda: self.client.v1.trading.trades.list(
        symbol=self.symbol,
        start_time=start,
        end_time=end,
        limit=TRADES_PAGE,
        offset=current,
      )
    )
    rows = page.get('data', [])
    yield [parse_trade(row) for row in rows]
    offset += len(rows)
    if not rows or offset >= (page.get('total') or 0):
      return


@asynccontextmanager
async def trades_stream(
  self: 'MarketMixin',
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
):
  """Subscribe to the market's own trades."""

  async def parsed(updates: AsyncIterable[MyTradeUpdate]) -> AsyncIterable[Trade]:
    async for update in updates:
      yield parse_update(update)

  async with self.subscribe_trades(queue_size=queue_size, overflow=overflow) as stream:
    yield parsed(stream)
