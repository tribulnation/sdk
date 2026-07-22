import asyncio
import logging

from typing_extensions import Collection, Mapping
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk import SDK, ApiError
from tribulnation.sdk.market import PerpStats, Settings, Ticker
from tribulnation.sdk.market.exchange import ticker_from_book

from tribulnation.dydx.core import wrap_exceptions
from .depth import parse_book
from .mixin import ExchangeMixin

FUNDING_INTERVAL = timedelta(hours=1)
"""dYdX settles funding every hour, on the hour."""

@wrap_exceptions
async def perp_stats(self: ExchangeMixin, markets: Collection[str] | None = None) -> Mapping[str, PerpStats]:
  """Fetch pricing and funding stats for every perp market in one call.

  The indexer's `/perpetualMarkets` payload already covers every market, so this
  is a single request yielding a consistent cross-section. dYdX reports no mark
  price, so `mark` is always `None`.

  Args:
    markets: Market tickers to keep. `None` keeps every market.

  Returns:
    A mapping of market ticker to its `PerpStats`.

  References:
    - [dYdX API docs](https://docs.dydx.xyz/types/perpetual_market)
  """
  perpetual_markets = await self.shared.load_markets(refetch=True)
  now = datetime.now().astimezone()
  next_time = now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL
  wanted = list(perpetual_markets) if markets is None else list(markets)

  stats: dict[str, PerpStats] = {}
  for ticker in wanted:
    if (market := perpetual_markets.get(ticker)) is None:
      raise ValueError(f'Market not found: {ticker}')
    if (price := market.get('oraclePrice')) is None:
      raise ApiError(f'Oracle price unavailable for {ticker}')
    open_interest = market.get('openInterest')
    stats[ticker] = PerpStats(
      index=Decimal(price),
      funding=Decimal(market['nextFundingRate']),
      next_funding_time=next_time,
      funding_interval=FUNDING_INTERVAL,
      open_interest=Decimal(open_interest) if open_interest is not None else None,
    )
  return stats

@SDK.method
@wrap_exceptions
async def fetch_order_book(self: ExchangeMixin, market_id: str):
  raw = await self.shared.client.indexer.data.get_order_book(market_id)
  return parse_book(raw)

@wrap_exceptions
async def tickers(
  self: ExchangeMixin, markets: Collection[str] | None = None, *, settings: Settings = {},
) -> Mapping[str, Ticker]:
  """Fetch ticker snapshots for every perp market in one call.

  Args:
    markets: Market tickers to keep. `None` keeps every market.
    settings: Venue settings. `dydx.tickers_fetch_depth` controls whether
      order books are fetched (default `True`), and
      `dydx.tickers_depth_concurrent` controls their concurrency (default 20).

  Returns:
    A mapping of market ticker to its `Ticker`.
  """
  perpetual_markets = await self.shared.load_markets(refetch=True)
  wanted = list(perpetual_markets) if markets is None else list(markets)

  result: dict[str, Ticker] = {}
  for ticker_name in wanted:
    if (market := perpetual_markets.get(ticker_name)) is None:
      raise ValueError(f'Market not found: {ticker_name}')
    price = market.get('oraclePrice')
    result[ticker_name] = Ticker(
      last=Decimal(price) if price is not None else None,
      base_volume_24h=Decimal(market['volume24H']),
    )

  venue_settings = settings.get('dydx', {})
  if not venue_settings.get('tickers_fetch_depth', True):
    return result

  concurrency = venue_settings.get('tickers_depth_concurrent', 20)
  sem = asyncio.Semaphore(concurrency)

  async def _enrich(market_id: str) -> None:
    async with sem:
      try:
        book = await fetch_order_book(self, market_id)
        bbo = ticker_from_book(book)
        t = result[market_id]
        t.bid, t.ask = bbo.bid, bbo.ask
        t.bid_qty, t.ask_qty = bbo.bid_qty, bbo.ask_qty
      except Exception as exc:
        logging.warning('tickers: %s book fetch failed: %s', market_id, exc)

  await asyncio.gather(*(_enrich(m) for m in wanted))
  return result
