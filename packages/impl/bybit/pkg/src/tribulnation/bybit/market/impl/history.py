"""Paged account history sweeps for one market.

Every page is fetched through `call_bybit`, so the retriable unit is the single
request that failed rather than the whole sweep -- a throttled page 7 of 12 retries
in place instead of restarting from page 1.
"""

from typing_extensions import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.market import FundingPayment, FundingRate, Trade

from tribulnation.bybit.core import TRADE_WINDOW, windows
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

  `market.funding_history` has no cursor -- it answers one time window with at most
  `limit` rows -- so the client's pager walks it backwards by moving the upper bound.

  An open upper bound is resolved to now rather than passed on: Bybit rejects a
  `startTime` sent without an `endTime` outright (`10001: Time Is Invalid`), while it
  answers an `endTime` with no `startTime` normally.
  """
  paging = self.client.market.funding_history_paged(
    'linear',
    symbol=self.symbol,
    start_time=start,
    end_time=end if end is not None else datetime.now(timezone.utc),
    limit=FUNDING_PAGE,
    validate=self.validate,
  )
  async for rows in paging.via(self.call_bybit):
    yield [
      FundingRate(rate=r['fundingRate'], time=r['fundingRateTimestamp']) for r in rows
    ]


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
