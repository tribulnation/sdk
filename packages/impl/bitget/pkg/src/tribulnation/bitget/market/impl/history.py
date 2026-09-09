"""Paged history sweeps for one market.

Every page is fetched through `call`, so the retriable unit is the single request that
failed rather than the whole sweep.
"""

from typing_extensions import AsyncIterator, Sequence
from datetime import datetime

from tribulnation.sdk.market import FundingRate, Trade

from .mixin import MarketMixin
from .parse import PERP, parse_mix_fill, parse_spot_fill, parse_uta_fill
from .util import HISTORY_WINDOW, PAGE, windows


async def trades_history(
  self: MarketMixin, start: datetime, end: datetime
) -> AsyncIterator[Sequence[Trade]]:
  """Walk this market's own fills, one page at a time, in 90-day windows.

  UTA's fill history has no symbol filter, so its rows are narrowed here.
  """
  uta = await self.is_uta()
  for lower, upper in windows(start, end, HISTORY_WINDOW):
    if uta:
      paging = self.client.uta.trade.order.fills_paged(
        self.product,
        start_time=lower,
        end_time=upper,
        limit=PAGE,
        validate=self.validate,
      )
      async for rows in paging.via(self.call):
        yield [parse_uta_fill(f) for f in rows if f['symbol'] == self.symbol]
    elif self.product == 'SPOT':
      # No paged variant: pages by `idLessThan`, the last row's trade id, and a page
      # shorter than the limit is the last one.
      cursor: str | None = None
      while True:
        rows = await self.call(
          lambda: self.client.classic.spot.order.fills(
            symbol=self.symbol,
            start_time=lower,
            end_time=upper,
            limit=PAGE,
            id_less_than=cursor,
            validate=self.validate,
          )
        )
        yield [parse_spot_fill(f) for f in rows]
        if len(rows) < PAGE:
          break
        cursor = rows[-1]['tradeId']
    else:
      paging = self.client.classic.mix.order.fills_paged(
        symbol=self.symbol,
        product_type=self.product,
        start_time=lower,
        end_time=upper,
        limit=PAGE,
        validate=self.validate,
      )
      async for rows in paging.via(self.call):
        yield [parse_mix_fill(f) for f in rows]


async def funding_rates(
  self: MarketMixin, start: datetime | None, end: datetime | None
) -> AsyncIterator[Sequence[FundingRate]]:
  """Walk this market's settled funding rates, newest page first.

  The endpoint pages by number, not by time, so the window is applied here: pages are
  read newest-first and the walk stops once a page reaches back past `start`.
  """
  paging = self.client.classic.mix.market.funding.rate_history_paged(
    self.symbol, product_type=PERP, page_size=PAGE, validate=self.validate
  )
  async for rows in paging.via(self.call):
    yield [
      FundingRate(rate=r['fundingRate'], time=r['fundingTime'])
      for r in rows
      if (start is None or r['fundingTime'] >= start)
      and (end is None or r['fundingTime'] <= end)
    ]
    if start is not None and rows and rows[-1]['fundingTime'] < start:
      break
