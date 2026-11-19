"""The perpetual exchange: discovery, bulk snapshots and exchange-wide history."""

from dataclasses import dataclass
import asyncio
from datetime import datetime, timedelta, timezone

from typing_extensions import (
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
  cast,
  overload,
)
from typed_evedex.exchange.market.order_book import OrderBook
from typed_evedex.schemas import Instrument
from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import (
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  PerpCollateral,
  PerpExchange,
  PerpStats,
  Settings,
  Ticker,
  Trade,
)

from ..core import FUNDING_SETTLEMENT, listed
from . import account, history
from .common import Public
from .markets import NO_FUNDING_PAYMENTS, EvedexPerpMarket, index_price, next_funding


TOP_OF_BOOK_CONCURRENCY = 10
"""Best bid/ask requests in flight at once, one per market."""


def ticker(row: Instrument, top: OrderBook) -> Ticker:
  """The best bid and ask from the book's top (`marketLevel=1`), last price and 24h
  volumes (`volume` in the base asset, `volumeBase` in USD) from the instrument."""
  bid = top['bids'][0] if top['bids'] else None
  ask = top['asks'][0] if top['asks'] else None
  return Ticker(
    last=row['lastPrice'],
    bid=None if bid is None else bid['price'],
    ask=None if ask is None else ask['price'],
    bid_qty=None if bid is None else bid['quantity'],
    ask_qty=None if ask is None else ask['quantity'],
    base_volume_24h=row['volume'],
    quote_volume_24h=row['volumeBase'],
  )


@dataclass(frozen=True, kw_only=True)
class EvedexPerpExchange(Public, PerpExchange):
  """Every perpetual, backed by the account's one cross-margin balance."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Every listed instrument (`visibility: all`), by name."""
    rows = await self.shared.load_instruments()
    return [name for name, row in rows.items() if listed(row)]

  async def market(self, market_id: str, /) -> EvedexPerpMarket:
    """A market by instrument name, delisted ones included."""
    row = await self.shared.instrument(market_id)
    return EvedexPerpMarket(shared=self.shared, name=row['name'])

  async def metrics(self, markets: Collection[str] | None) -> dict[str, Instrument]:
    """The listed instruments among `markets` (every listed one when `None`) with their
    market metrics, from one `instruments(fields='metrics')` read."""
    rows = await self.shared.call(
      lambda: self.shared.client.exchange.market.instruments('metrics')
    )
    # `fields='metrics'` sends full records with metrics; the declared return is the
    # union of every `fields` shape (typed-client-issues.md).
    wanted = None if markets is None else set(markets)
    return {
      r['name']: r
      for r in cast(list[Instrument], rows)
      if listed(r) and (wanted is None or r['name'] in wanted)
    }

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, Ticker]:
    """Best bid and ask, last price and 24h volumes of the listed instruments: one
    instruments read, then one top-of-book request per market, concurrently."""
    if markets is not None and not markets:
      return {}
    rows = await self.metrics(markets)
    gate = asyncio.Semaphore(TOP_OF_BOOK_CONCURRENCY)

    async def top(name: str) -> OrderBook:
      """The market's best bid and ask."""
      async with gate:
        return await self.shared.call(
          lambda: self.shared.client.exchange.market.order_book(
            instrument=name, market_level='1'
          )
        )

    tops = await asyncio.gather(*(top(name) for name in rows))
    return {name: ticker(row, t) for (name, row), t in zip(rows.items(), tops)}

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, PerpStats]:
    """Index, mark, open interest (base units) and the next hourly funding settlement
    of the listed instruments, from one request."""
    if markets is not None and not markets:
      return {}
    rows = await self.metrics(markets)
    now = datetime.now(timezone.utc)
    stats: dict[str, PerpStats] = {}
    for name, row in rows.items():
      funding = next_funding(row, now=now)
      stats[name] = PerpStats(
        index=index_price(row),
        mark=row['markPrice'],
        funding=funding.rate,
        next_funding_time=funding.time,
        funding_interval=FUNDING_SETTLEMENT,
        open_interest=row['openInterest'],
      )
    return stats

  @overload
  def trades_history(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeTrade]: ...
  @overload
  def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[Trade]: ...
  @PaginatedResponse.lift
  async def trades_history(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """The account's fills, of one market or every market."""
    async for page in history.trades_history(self.shared, market_id, start, end):
      yield page

  @overload
  def funding_payments(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeFundingPayment]: ...
  @overload
  def funding_payments(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]: ...
  @PaginatedResponse.lift
  async def funding_payments(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """Not supported: the account ledger's funding entries name no instrument."""
    raise NotImplementedError(NO_FUNDING_PAYMENTS)
    yield

  async def perp_collateral(
    self, market_id: str | None = None, /, *, ttl: timedelta | None = None
  ) -> PerpCollateral:
    """The account's one cross bucket, whatever the market."""
    if market_id is not None:
      await self.shared.instrument(market_id)
    return await account.collateral(self.shared, ttl=ttl)
