"""Fill history and the live fill stream for one product."""

from typing_extensions import AsyncIterable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.market import Trade

from typed_coinbase.app.advanced_trade.http.orders.historical.fills import Fill

from .mixin import MarketMixin


def parse_fill(fill: Fill, *, quote: str) -> Trade | None:
  """Map one Advanced Trade fill onto a `Trade`.

  Returns `None` for a fill with no `trade_time`: the field is optional upstream and
  `Trade.time` is required, so there is nothing honest to put there.
  """
  time = fill.get('trade_time')
  if time is None:
    return None
  sign = 1 if fill.get('side') == 'BUY' else -1
  commission = fill.get('commission')
  fee = (
    Trade.Fee(amount=commission, asset=quote)
    if commission is not None and commission != 0
    else None
  )
  return Trade(
    id=fill.get('trade_id'),
    price=fill.get('price') or Decimal(0),
    qty=sign * (fill.get('size') or Decimal(0)),
    time=time,
    maker=fill.get('liquidity_indicator') == 'MAKER',
    fee=fee,
    details=fill,
  )


async def trades_history(
  self: MarketMixin, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Stream the product's fill history, one page per upstream page."""
  paging = self.app.advanced_trade.http.orders.historical.fills_paged(
    product_ids=[self.product_id],
    start_sequence_timestamp=start,
    end_sequence_timestamp=end,
  )
  quote = self.quote_asset
  async for page in paging.via(self.call_app):
    trades = [parse_fill(fill, quote=quote) for fill in page]
    yield [trade for trade in trades if trade is not None]


@asynccontextmanager
async def trades_stream(
  self: MarketMixin, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
):
  """Subscribe to this product's fills, reconstructed from the `user` channel.

  Best-effort, and lossier than `trades_history`: see
  `tribulnation.coinbase.core.streams.user_trades_stream`.
  """
  async with self.subscribe_user_trades(
    queue_size=queue_size, overflow=overflow
  ) as user_trades:

    async def stream() -> AsyncIterable[Trade]:
      async for product_id, trade in user_trades:
        if product_id == self.product_id:
          yield trade

    yield stream()
