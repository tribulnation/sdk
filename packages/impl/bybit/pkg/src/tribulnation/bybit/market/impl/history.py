"""Paged account history sweeps for one market.

Every page is fetched through `call_bybit`, so the retriable unit is the single
request that failed rather than the whole sweep -- a throttled page 7 of 12 retries
in place instead of restarting from page 1.
"""

from typing_extensions import AsyncIterator, Sequence
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.market import FundingPayment, FundingRate, Trade

from tribulnation.bybit.core import MILLISECOND, TRADE_WINDOW, windows
from .mixin import MarketMixin
from .parse import parse_execution

FUNDING_PAGE = 200
"""Rows per `market.funding_history` page; Bybit's documented maximum."""


async def trades_history(
  self: MarketMixin, start: datetime, end: datetime
) -> AsyncIterator[Sequence[Trade]]:
  """Walk this market's own fills, one cursor page at a time."""
  for lower, upper in windows(start, end, TRADE_WINDOW):
    cursor: str | None = None
    while True:
      page = await self.call_bybit(
        lambda: self.client.trade.trade_history(
          self.category,
          symbol=self.symbol,
          start_time=lower,
          end_time=upper,
          exec_type='Trade',
          cursor=cursor,
          validate=self.validate,
        )
      )
      yield [parse_execution(t) for t in page['list']]
      cursor = page.get('nextPageCursor')
      if not cursor:
        break


async def funding_rates(
  self: MarketMixin, start: datetime | None, end: datetime | None
) -> AsyncIterator[Sequence[FundingRate]]:
  """Walk this market's settled funding rates, newest page first.

  `market.funding_history` has no cursor: it answers one time window with at most
  `limit` rows, newest first. Each page therefore moves the window's upper bound to
  just before the oldest row it returned, and a short page ends the walk.
  """
  upper = end
  while True:
    page = await self.call_bybit(
      lambda: self.client.market.funding_history(
        'linear',
        symbol=self.symbol,
        start_time=start,
        end_time=upper,
        limit=FUNDING_PAGE,
        validate=self.validate,
      )
    )
    rows = page['list']
    if not rows:
      return
    yield [
      FundingRate(rate=r['fundingRate'], time=r['fundingRateTimestamp']) for r in rows
    ]
    if len(rows) < FUNDING_PAGE:
      return
    upper = min(r['fundingRateTimestamp'] for r in rows) - MILLISECOND
    if start is not None and upper < start:
      return


async def funding_payments(
  self: MarketMixin, start: datetime, end: datetime
) -> AsyncIterator[Sequence[FundingPayment]]:
  """Walk this market's funding settlements out of the account transaction log.

  `account.transaction_log` has no symbol filter, so the rows are narrowed here.
  """
  for lower, upper in windows(start, end, TRADE_WINDOW):
    cursor: str | None = None
    while True:
      page = await self.call_bybit(
        lambda: self.client.account.transaction_log(
          category='linear',
          type='SETTLEMENT',
          start_time=lower,
          end_time=upper,
          cursor=cursor,
          validate=self.validate,
        )
      )
      yield [
        # A settlement charged to the account is money paid, which the SDK's
        # `FundingPayment` reports positive; Bybit signs `funding` the other way.
        FundingPayment(amount=-Decimal(e['funding']), time=e['transactionTime'])
        for e in page['list']
        if e['symbol'] == self.symbol and 'funding' in e and e['funding']
      ]
      cursor = page.get('nextPageCursor')
      if not cursor:
        break
