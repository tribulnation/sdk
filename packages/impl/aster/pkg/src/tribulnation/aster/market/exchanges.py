"""Spot and perpetual exchanges: discovery, bulk tickers and perpetual statistics.

Per-market methods use the SDK's default delegation to `market(market_id)`.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing_extensions import (
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
  TypedDict,
  overload,
)
from decimal import Decimal
import asyncio
from typed_aster.futures.market.funding_info import FundingInfo
from typed_aster.futures.market.schemas import FuturesMarkPrice
from tribulnation.sdk.market import (
  Exchange,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  PerpCollateral,
  PerpExchange as SDKPerpExchange,
  PerpStats,
  Settings,
  Ticker,
  Trade,
)
from tribulnation.sdk.core import PaginatedResponse, SDK
from tribulnation.sdk.core.concurrency import managed_tasks
from ..core import Public
from .markets import (
  PerpMarket,
  SpotMarket,
  cross_collateral,
  exchange_trade,
  spot_trade_rows,
  trade_windows,
)

OPEN_INTEREST_MARKETS = 5
"""Most explicitly requested contracts `perp_stats` reads open interest for.

Open interest is served one symbol per request, so larger and unfiltered requests
leave it `None` rather than issuing hundreds of reads.
"""


class Stats(TypedDict):
  """The native 24h ticker fields shared by spot and futures."""

  symbol: str
  lastPrice: Decimal
  volume: Decimal
  quoteVolume: Decimal


class Quote(TypedDict):
  """The native best bid/ask fields shared by spot and futures."""

  symbol: str
  bidPrice: Decimal
  bidQty: Decimal
  askPrice: Decimal
  askQty: Decimal


def positive(value: Decimal) -> Decimal | None:
  """Aster reports an empty book side, or a symbol never traded, as price zero."""
  return value if value > 0 else None


def join_tickers(
  stats: Sequence[Stats], quotes: Sequence[Quote], symbols: Collection[str]
) -> dict[str, Ticker]:
  """Join rolling 24h statistics with best bid/ask by symbol; empty sides are `None`."""
  books = {q['symbol']: q for q in quotes}
  result: dict[str, Ticker] = {}
  for row in stats:
    if row['symbol'] not in symbols:
      continue
    quote = books.get(row['symbol'])
    bid = positive(quote['bidPrice']) if quote else None
    ask = positive(quote['askPrice']) if quote else None
    result[row['symbol']] = Ticker(
      last=positive(row['lastPrice']),
      base_volume_24h=row['volume'],
      quote_volume_24h=row['quoteVolume'],
      bid=bid,
      ask=ask,
      bid_qty=quote['bidQty'] if quote and bid is not None else None,
      ask_qty=quote['askQty'] if quote and ask is not None else None,
    )
  return result


def join_perp_stats(
  premiums: Sequence[FuturesMarkPrice],
  configs: Sequence[FundingInfo],
  symbols: Collection[str],
  interest: Mapping[str, Decimal] = {},
) -> dict[str, PerpStats]:
  """Join premium-index rows with funding intervals and open interest by symbol.

  A missing or null interval (testnet serves some) is `None`, not an error; so is the
  open interest of a symbol absent from `interest`.
  """
  hours = {c['symbol']: c['fundingIntervalHours'] for c in configs}
  result: dict[str, PerpStats] = {}
  for row in premiums:
    if row['symbol'] not in symbols:
      continue
    interval = hours.get(row['symbol'])
    result[row['symbol']] = PerpStats(
      index=row['indexPrice'],
      mark=row['markPrice'],
      funding=row['lastFundingRate'],
      next_funding_time=row['nextFundingTime'],
      funding_interval=timedelta(hours=interval) if interval is not None else None,
      open_interest=interest.get(row['symbol']),
    )
  return result


def selected(available: Collection[str], markets: Collection[str] | None) -> set[str]:
  """The requested subset of available symbols, or all of them."""
  return set(available) if markets is None else set(available) & set(markets)


@dataclass(frozen=True, kw_only=True)
class SpotExchange(Public, Exchange):
  """Aster spot."""

  @property
  def exchange_id(self) -> str:
    """The spot exchange ID."""
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """List native symbols currently trading."""
    return list(await self.shared.spot_symbols())

  async def market(self, market_id: str, /) -> SpotMarket:
    """Resolve a trading symbol."""
    if market_id not in await self.shared.spot_symbols():
      raise ValueError(f'Unknown Aster spot market: {market_id}')
    return SpotMarket(shared=self.shared, symbol=market_id)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Read 24h statistics and best bid/ask for all or the selected symbols."""
    if markets is not None and not markets:
      return {}
    symbols = selected(await self.shared.spot_symbols(refetch=True), markets)
    market = self.client.spot.market
    stats = await self.shared.call(market.ticker_24hr)
    quotes = await self.shared.call(market.book_ticker)
    return join_tickers(
      stats if isinstance(stats, list) else [stats],
      quotes if isinstance(quotes, list) else [quotes],
      symbols,
    )

  @overload
  def trades_history(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeTrade]: ...

  @overload
  def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[Trade]: ...

  @SDK.method
  @PaginatedResponse.lift
  async def trades_history(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Read fills for one pair or every pair, within inclusive bounds up to now.

    Exchange-wide reads come from symbol-less `userTrades` in seven-day windows,
    halving any window that fills a page. Mainnet only: testnet omits buy fills.
    """
    if market_id is not None:
      async for page in (await self.market(market_id)).trades_history(start, end):
        yield page
      return
    if start.tzinfo is None or end.tzinfo is None:
      raise ValueError('Trade history bounds must be timezone-aware')
    if not self.shared.mainnet:
      raise NotImplementedError(
        'Aster testnet spot trade history is not supported: userTrades omits buy fills'
      )
    for lower, upper in trade_windows(start, end, datetime.now(timezone.utc)):
      async for rows in spot_trade_rows(self.shared, lower, upper):
        if page := [exchange_trade(r) for r in rows if start <= r['time'] <= end]:
          yield page


@dataclass(frozen=True, kw_only=True)
class PerpExchange(Public, SDKPerpExchange):
  """Aster linear perpetuals: one cross-margin bucket, plus isolated positions."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange ID."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """List perpetual contracts currently trading."""
    return list(await self.shared.perp_symbols())

  async def market(self, market_id: str, /) -> PerpMarket:
    """Resolve a trading perpetual."""
    if market_id not in await self.shared.perp_symbols():
      raise ValueError(f'Unknown Aster perpetual: {market_id}')
    return PerpMarket(shared=self.shared, symbol=market_id)

  @overload
  def funding_payments(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeFundingPayment]: ...

  @overload
  def funding_payments(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]: ...

  @SDK.method
  @PaginatedResponse.lift
  async def funding_payments(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """Read funding for one market or every perpetual market."""
    if market_id is not None:
      async for page in (await self.market(market_id)).funding_payments(start, end):
        yield page
      return
    if start.tzinfo is None or end.tzinfo is None:
      raise ValueError('Funding history bounds must be timezone-aware')
    pages = self.client.futures.account.income_paged(
      income_type='FUNDING_FEE', start_time=start, end_time=end, limit=1000
    )
    async for page in pages.via(self.shared.call):
      yield [
        ExchangeFundingPayment(
          market_id=r['symbol'], amount=r['income'], time=r['time']
        )
        for r in page
      ]

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Read 24h statistics and best bid/ask for all or the selected contracts."""
    if markets is not None and not markets:
      return {}
    symbols = selected(await self.shared.perp_symbols(refetch=True), markets)
    market = self.client.futures.market
    stats = await self.shared.call(market.ticker_24hr)
    quotes = await self.shared.call(market.book_ticker)
    return join_tickers(
      stats if isinstance(stats, list) else [stats],
      quotes if isinstance(quotes, list) else [quotes],
      symbols,
    )

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Read pricing and funding for all or the selected contracts in two bulk calls.

    Open interest (base units) is read per contract, concurrently, only when at most
    `OPEN_INTEREST_MARKETS` contracts are named explicitly; otherwise it is `None`,
    since the venue has no bulk source. Observations are not atomic.
    """
    if markets is not None and not markets:
      return {}
    symbols = selected(await self.shared.perp_symbols(refetch=True), markets)
    market = self.client.futures.market
    premiums = await self.shared.call(market.premium_index)
    configs = await self.shared.call(market.funding_info)
    interest: dict[str, Decimal] = {}
    if markets is not None and len(symbols) <= OPEN_INTEREST_MARKETS:
      interest = await self.open_interest(symbols)
    return join_perp_stats(
      premiums if isinstance(premiums, list) else [premiums],
      configs,
      symbols,
      interest,
    )

  async def open_interest(self, symbols: Collection[str]) -> dict[str, Decimal]:
    """Read each contract's open interest, in base units, one retried request each."""
    market = self.client.futures.market

    async def read(symbol: str) -> tuple[str, Decimal]:
      """One contract's open interest."""
      row = await self.shared.call(lambda: market.open_interest(symbol))
      return symbol, row['openInterest']

    async with managed_tasks(read(symbol) for symbol in symbols) as tasks:
      return dict(await asyncio.gather(*tasks))

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """Read the cross-margin bucket, or a market's own (cross or isolated) bucket."""
    if market_id is not None:
      return await (await self.market(market_id)).perp_collateral()
    return cross_collateral(await self.shared.futures_account())
