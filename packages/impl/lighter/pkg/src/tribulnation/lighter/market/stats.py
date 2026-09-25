"""Tickers, perpetual stats and predicted funding, from the `*market_stats` snapshots."""

from datetime import datetime
from decimal import Decimal

from typing_extensions import Collection, Literal, Mapping
from typed_lighter.schemas import MarketSelector, MarketStats, SpotMarketStats
from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import NextFunding, PerpStats, Ticker

from ..core import FUNDING_INTERVAL, Shared, percent


def price_or_none(value: Decimal | Literal['']) -> Decimal | None:
  """A stats price, or `None` where the venue sends `""` (no such side)."""
  return None if value == '' else value


async def read_perp_snapshot(
  shared: Shared, selector: MarketSelector
) -> dict[int, MarketStats]:
  """The `market_stats` subscribe snapshot: every perp's live stats, or one market's."""
  async with shared.client.streams.market_stats(selector) as stream:
    async for frame in stream:
      stats = frame['market_stats']
      # One market's frame is its stats; `all`'s maps market ids to stats.
      rows = [stats] if 'market_id' in stats else stats.values()
      return {s['market_id']: s for s in rows}  # type: ignore[union-attr]
  raise ApiError('Lighter market_stats stream closed before its snapshot')


async def read_spot_snapshot(shared: Shared) -> dict[int, SpotMarketStats]:
  """The `spot_market_stats:all` subscribe snapshot."""
  async with shared.client.streams.spot_market_stats('all') as stream:
    async for frame in stream:
      stats = frame['spot_market_stats']
      # One market's frame is its stats; `all`'s maps market ids to stats.
      rows = [stats] if 'market_id' in stats else stats.values()
      return {s['market_id']: s for s in rows}  # type: ignore[union-attr]
  raise ApiError('Lighter spot_market_stats stream closed before its snapshot')


async def perp_snapshot(
  shared: Shared, selector: MarketSelector
) -> dict[int, MarketStats]:
  """The perp snapshot, as one retried request."""
  return await shared.call(lambda: read_perp_snapshot(shared, selector))


async def spot_snapshot(shared: Shared) -> dict[int, SpotMarketStats]:
  """The spot snapshot, as one retried request."""
  return await shared.call(lambda: read_spot_snapshot(shared))


def selected(markets: Collection[str] | None, available: Collection[int]) -> list[int]:
  """The requested market ids present in a snapshot, or all of them."""
  if markets is None:
    return list(available)
  wanted = {int(m) for m in markets if m.isdigit()}
  return [m for m in available if m in wanted]


def ticker(s: MarketStats | SpotMarketStats) -> Ticker:
  """Last price, best bid/ask and 24h volumes; the venue sends no best-level sizes."""
  return Ticker(
    last=s['last_trade_price'],
    bid=price_or_none(s['best_bid_price']),
    ask=price_or_none(s['best_ask_price']),
    base_volume_24h=Decimal(str(s['daily_base_token_volume'])),
    quote_volume_24h=Decimal(str(s['daily_quote_token_volume'])),
  )


async def perp_tickers(
  shared: Shared, markets: Collection[str] | None
) -> Mapping[str, Ticker]:
  """Tickers of the requested perpetuals."""
  if markets is not None and not markets:
    return {}
  stats = await perp_snapshot(shared, 'all')
  return {str(m): ticker(stats[m]) for m in selected(markets, stats)}


async def spot_tickers(
  shared: Shared, markets: Collection[str] | None
) -> Mapping[str, Ticker]:
  """Tickers of the requested spot markets."""
  if markets is not None and not markets:
    return {}
  stats = await spot_snapshot(shared)
  return {str(m): ticker(stats[m]) for m in selected(markets, stats)}


def next_settlement(last: datetime) -> datetime:
  """The hour after the last settlement (whose stamp carries a few ms of jitter)."""
  return last.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL


async def perp_stats(
  shared: Shared, markets: Collection[str] | None
) -> Mapping[str, PerpStats]:
  """Index, mark and predicted funding from `market_stats`; base-unit open interest from
  `orderBookDetails` (`market_stats` reports it in USDC)."""
  if markets is not None and not markets:
    return {}
  stats = await perp_snapshot(shared, 'all')
  await shared.load_details(refetch=True)
  return {
    str(m): PerpStats(
      index=stats[m]['index_price'],
      mark=stats[m]['mark_price'],
      funding=percent(stats[m]['current_funding_rate']),
      next_funding_time=next_settlement(stats[m]['funding_timestamp']),
      funding_interval=FUNDING_INTERVAL,
      open_interest=Decimal(str(shared.perps[m]['open_interest']))
      if m in shared.perps
      else None,
    )
    for m in selected(markets, stats)
  }


async def next_funding(shared: Shared, market_id: int) -> NextFunding:
  """The venue's estimate of the next hourly settlement's rate (percent, positive when
  longs pay), with the premium it is computed from."""
  stats = (await perp_snapshot(shared, market_id))[market_id]
  return NextFunding(
    rate=percent(stats['current_funding_rate']),
    time=next_settlement(stats['funding_timestamp']),
    interval=FUNDING_INTERVAL,
    premium=percent(stats['premium']),
  )
