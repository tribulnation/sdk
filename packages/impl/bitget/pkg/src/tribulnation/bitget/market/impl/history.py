"""Paged history sweeps for one market.

Every page is fetched through `call`, so the retriable unit is the single request that
failed rather than the whole sweep.
"""

from typing_extensions import AsyncIterator, Literal, Mapping, Sequence
from datetime import datetime, timedelta

from tribulnation.sdk.market import FundingRate, InterestPayment, Trade
from typed_bitget.uta.account.financial_records import FinancialRecord

from .mixin import MarketMixin, VenueMixin
from .parse import (
  MARGIN_COIN,
  MarginInstrument,
  futures_product,
  parse_mix_fill,
  parse_spot_fill,
  parse_uta_fill,
)
from .util import HISTORY_WINDOW, PAGE, windows

INTEREST = 'INTEREST_SETTLEMENT_OUT'
"""The UTA ledger type of a borrow-interest charge ("interest deducted from the
account", Bitget's UTA enumeration of financial-record types)."""
LEDGER_CATEGORIES: Sequence[
  Literal['SPOT', 'MARGIN', 'USDT-FUTURES', 'COIN-FUTURES', 'USDC-FUTURES']
] = ('MARGIN', 'SPOT', 'USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES')
"""Every category the ledger is addressed by. Debt is pool-wide on a UTA, so an
interest row is not documented under any one product: each is read, rows deduplicated
by ID."""
LEDGER_WINDOW = timedelta(days=30)
"""Window per ledger request, well inside the 90 days of history the venue keeps."""


async def trades_history(
  self: MarketMixin, start: datetime, end: datetime
) -> AsyncIterator[Sequence[Trade]]:
  """Walk this market's own fills, one page at a time, in 90-day windows.

  UTA's fill history has no symbol filter, so its rows are narrowed here.
  """
  self.require_account_surface()
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
        product_type=futures_product(self.product),
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
  product = futures_product(self.product)
  paging = self.client.classic.mix.market.funding.rate_history_paged(
    self.symbol, product_type=product, page_size=PAGE, validate=self.validate
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


def parse_interest(record: FinancialRecord) -> InterestPayment:
  """Map one UTA ledger interest row onto an `InterestPayment`; the ledger's `amount`
  is already signed, negative for a charge."""
  return InterestPayment(
    time=record['ts'], asset=record['coin'], amount=record['amount']
  )


def interest_pair(instruments: Mapping[str, MarginInstrument], coin: str) -> str | None:
  """The one margin pair that reports `coin`'s borrow interest, if any pair borrows it.

  Interest is charged per coin on the unified pool, not per pair, and the ledger row
  names no pair: every pair of the coin (`LINKUSDT`, `LINKUSDC`) would read the same
  rows. So one pair owns them, the USDT-quoted one when listed, else the first symbol,
  and summing interest over every margin market counts each charge once.

  Args:
    instruments: The `MARGIN` catalogue, keyed by symbol.
    coin: The borrowed base coin, e.g. `LIT`.
  """
  pairs = sorted(
    (row['quoteCoin'] != MARGIN_COIN, symbol)
    for symbol, row in instruments.items()
    if row['baseCoin'] == coin
  )
  if pairs:
    return pairs[0][1]


async def interest_payments(
  self: VenueMixin, start: datetime, end: datetime, *, coin: str | None
) -> AsyncIterator[Sequence[InterestPayment]]:
  """Walk the UTA ledger's borrow-interest charges, one page at a time.

  Args:
    start: Inclusive start of the window.
    end: Inclusive end of the window.
    coin: Keep one borrowed coin, e.g. `LIT`; `None` keeps every coin.
  """
  seen: set[str] = set()
  for category in LEDGER_CATEGORIES:
    for lower, upper in windows(start, end, LEDGER_WINDOW):
      paging = self.client.uta.account.financial_records_paged(
        category,
        coin=coin,
        type=INTEREST,
        start_time=lower,
        end_time=upper,
        limit=PAGE,
        validate=self.validate,
      )
      async for rows in paging.via(self.call):
        fresh = [r for r in rows if r['id'] not in seen]
        seen.update(r['id'] for r in fresh)
        yield [parse_interest(r) for r in fresh]
