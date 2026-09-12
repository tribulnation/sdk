"""Public snapshots for Binance's actively trading USD-M perpetuals."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
import asyncio

from tribulnation.sdk.core.concurrency import managed_tasks
from tribulnation.sdk.market import (
  PerpExchange as _PerpExchange,
  PerpStats,
  Settings,
  Ticker,
)

from .impl import (
  SharedMixin,
  wrap_exceptions,
)
from .perp_market import PerpMarket


@dataclass(frozen=True, kw_only=True)
class PerpExchange(SharedMixin, _PerpExchange):
  """Binance's USD-M futures exchange."""

  @property
  def venue_id(self) -> str:
    return 'binance'

  @property
  def exchange_id(self) -> str:
    return 'usdm'

  @wrap_exceptions
  async def markets(self) -> Sequence[str]:
    symbols = await self.shared.load_perp_symbols()
    return [
      s['symbol']
      for s in symbols.values()
      if s['contractType'] == 'PERPETUAL' and s['status'] == 'TRADING'
    ]

  async def market(self, market_id: str, /) -> PerpMarket:
    return PerpMarket(shared=self.shared, symbol=market_id)

  async def selected_markets(self, markets: Collection[str] | None) -> list[str]:
    """Discover active perpetuals and reject unknown explicitly requested IDs."""
    available = await self.markets()
    if markets is None:
      return list(available)
    wanted = set(markets)
    if missing := wanted.difference(available):
      raise ValueError(f'Binance USD-M perpetual markets not found: {sorted(missing)}')
    return [symbol for symbol in available if symbol in wanted]

  @wrap_exceptions
  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Join bulk trade and book snapshots, excluding dated/inactive contracts.

    These public endpoints are separate snapshots, not an atomic observation.
    Missing book sides remain absent; missing trade rows fail visibly.
    """
    if markets is not None and not markets:
      return {}
    wanted = await self.selected_markets(markets)
    if not wanted:
      return {}
    api = self.client.usdm_futures.http.market
    trades = await self.call_binance(api.ticker_24hr)
    books = await self.call_binance(api.ticker_book)
    if not isinstance(trades, list) or not isinstance(books, list):
      raise ValueError('Binance bulk futures ticker endpoints must return lists.')
    by_symbol = {row['symbol']: row for row in trades}
    by_book = {row['symbol']: row for row in books}
    if missing := set(wanted).difference(by_symbol):
      raise ValueError(f'Binance futures tickers not found: {sorted(missing)}')
    result: dict[str, Ticker] = {}
    for symbol in wanted:
      trade = by_symbol[symbol]
      book = by_book.get(symbol)
      has_bid = book is not None and book['bidQty'] > 0
      has_ask = book is not None and book['askQty'] > 0
      result[symbol] = Ticker(
        last=trade['lastPrice'],
        base_volume_24h=trade['volume'],
        bid=book['bidPrice'] if book is not None and has_bid else None,
        bid_qty=book['bidQty'] if book is not None and has_bid else None,
        ask=book['askPrice'] if book is not None and has_ask else None,
        ask_qty=book['askQty'] if book is not None and has_ask else None,
      )
    return result

  @wrap_exceptions
  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Read public pricing/funding plus bounded per-symbol open interest.

    Funding uses Binance's latest premium-index rate and current interval override
    (eight hours otherwise). Open interest is in the contract's base units, not
    quote notional. At most five open-interest requests run concurrently; errors
    propagate after all outstanding work is cancelled and drained.
    """
    if markets is not None and not markets:
      return {}
    wanted = await self.selected_markets(markets)
    if not wanted:
      return {}
    api = self.client.usdm_futures.http.market
    premiums = await self.call_binance(api.premium_index)
    configs = await self.call_binance(api.funding_info)
    if not isinstance(premiums, list):
      raise ValueError('Binance bulk premium-index endpoint must return a list.')
    by_symbol = {row['symbol']: row for row in premiums}
    if missing := set(wanted).difference(by_symbol):
      raise ValueError(f'Binance futures premium rows not found: {sorted(missing)}')
    intervals = {row['symbol']: row['fundingIntervalHours'] for row in configs}
    sem = asyncio.Semaphore(5)

    async def snapshot(symbol: str) -> tuple[str, PerpStats]:
      """Combine one symbol's public observations without private account access."""
      async with sem:
        interest = await self.call_binance(lambda: api.open_interest(symbol))
      if interest['symbol'] != symbol:
        raise ValueError('Binance open-interest response has the wrong symbol.')
      premium = by_symbol[symbol]
      return symbol, PerpStats(
        index=premium['indexPrice'],
        mark=premium['markPrice'],
        funding=premium['lastFundingRate'],
        next_funding_time=premium['nextFundingTime'],
        funding_interval=timedelta(hours=intervals.get(symbol, 8)),
        open_interest=interest['openInterest'],
      )

    async with managed_tasks(snapshot(symbol) for symbol in wanted) as tasks:
      return dict(await asyncio.gather(*tasks))
