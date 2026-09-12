"""Own-trade history and stream."""

from typing_extensions import TYPE_CHECKING, AsyncIterable, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.market import Trade

from typed_kraken.spot.account.trades_history import HistoricalTrade
from typed_kraken.streams.private.executions import ExecutionTradeEvent

if TYPE_CHECKING:
  from .mixin import MarketMixin

TRADES_PAGE = 100
"""Trades per page. `TradesHistory` clamps `limit` to 100."""


def parse_trade(txid: str, trade: HistoricalTrade, *, quote: str) -> Trade:
  """Map one historical fill onto a `Trade`.

  Args:
    txid: The trade's transaction id, the key it is listed under.
    trade: The fill.
    quote: The pair's quote asset, which `fee` is denominated in.
  """
  vol = trade.get('vol', Decimal(0))
  fee = trade.get('fee')
  trade_id = trade.get('trade_id')
  return Trade(
    id=str(trade_id) if trade_id is not None else txid,
    price=trade.get('price', Decimal(0)),
    qty=vol if trade.get('type') == 'buy' else -vol,
    time=trade['time'],
    maker=bool(trade.get('maker')),
    fee=Trade.Fee(amount=fee, asset=quote) if fee else None,
    details=trade,
  )


def parse_fill(event: ExecutionTradeEvent) -> Trade:
  """Map one streamed fill onto a `Trade`.

  Prices, quantities and fees arrive as JSON numbers, which the client keeps as
  `float`; each is transcribed through its shortest string representation.
  """
  qty = Decimal(str(event['last_qty']))
  fees = event.get('fees') or []
  return Trade(
    id=str(event['trade_id']),
    price=Decimal(str(event['last_price'])),
    qty=qty if event['side'] == 'buy' else -qty,
    time=event['timestamp'],
    maker=event['liquidity_ind'] == 'm',
    fee=Trade.Fee(amount=Decimal(str(fees[0]['qty'])), asset=fees[0]['asset'])
    if fees
    else None,
    details=event,
  )


async def trades_history(
  self: 'MarketMixin', start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Fetch the market's own-trade history, one page at a time, newest first.

  `start` is exclusive on the wire and in whole seconds, so it is sent one second
  early and the window is re-applied here to keep the SDK's inclusive bound.
  """
  quote = self.quote
  offset = 0
  while True:
    current = offset
    page = await self.call_kraken(
      lambda: self.client.spot.account.trades_history(
        pair=self.altname,
        start=int(start.timestamp()) - 1,
        end=int(end.timestamp()),
        ofs=current,
        limit=TRADES_PAGE,
      )
    )
    rows = page.get('trades') or {}
    yield [
      trade
      for txid, row in rows.items()
      if start <= (trade := parse_trade(txid, row, quote=quote)).time <= end
    ]
    offset += len(rows)
    if not rows or offset >= (page.get('count') or 0):
      return


@asynccontextmanager
async def trades_stream(
  self: 'MarketMixin',
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
):
  """Subscribe to the market's own fills, off the account-wide `executions` channel."""
  symbol = self.ws_symbol

  async def parsed(events: AsyncIterable[ExecutionTradeEvent]) -> AsyncIterator[Trade]:
    async for event in events:
      if event['symbol'] == symbol:
        yield parse_fill(event)

  async with self.subscribe_fills(queue_size=queue_size, overflow=overflow) as stream:
    yield parsed(stream)
