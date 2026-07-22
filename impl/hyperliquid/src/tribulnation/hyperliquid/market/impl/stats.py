import asyncio

from typing_extensions import Collection, Mapping
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk import SDK
from tribulnation.sdk.market import Book, PerpStats, Settings, Ticker
from tribulnation.sdk.market.exchange import ticker_from_book

from tribulnation.hyperliquid.core import wrap_exceptions
from .mixin import PerpMixin

FUNDING_INTERVAL = timedelta(hours=1)
"""Hyperliquid settles funding every hour, on the hour."""

@wrap_exceptions
async def perp_stats(
  self: PerpMixin, markets: Collection[str] | None = None, *, settings: Settings = {},
) -> Mapping[str, PerpStats]:
  """Fetch pricing and funding stats for the whole perp universe in one call.

  `metaAndAssetCtxs` already returns a context for every asset in the universe,
  so this is a single request yielding a consistent cross-section.

  Args:
    markets: Asset names to keep. `None` keeps the whole universe.
    settings: Venue settings. `hyperliquid.index_price` selects `'oracle'`
      (default) or `'mark'` as the `index` field, matching `index()`.

  Returns:
    A mapping of asset name to its `PerpStats`.

  References:
    - [Hyperliquid API docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals#retrieve-perpetuals-asset-contexts-includes-mark-price-current-funding-open-interest-etc)
  """
  _, perp_meta, asset_ctxs = await self.shared.load_perp_meta_for_dex(self.dex_name, refetch=True)
  now = datetime.now().astimezone()
  next_time = now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL
  use_mark = settings.get('hyperliquid', {}).get('index_price', 'oracle') == 'mark'
  wanted = None if markets is None else set(markets)

  stats: dict[str, PerpStats] = {}
  for asset, ctx in zip(perp_meta['universe'], asset_ctxs):
    name = asset['name']
    if wanted is not None and name not in wanted:
      continue
    mark = Decimal(px) if (px := ctx.get('markPx')) is not None else None
    oracle = Decimal(ctx['oraclePx'])
    stats[name] = PerpStats(
      index=mark if use_mark and mark is not None else oracle,
      mark=mark,
      funding=Decimal(ctx['funding']),
      next_funding_time=next_time,
      funding_interval=FUNDING_INTERVAL,
      open_interest=Decimal(oi) if (oi := ctx.get('openInterest')) is not None else None,
    )

  if wanted is not None and (missing := wanted - set(stats)):
    raise ValueError(f'Perps not found: {", ".join(sorted(missing))}')
  return stats


@SDK.method
@wrap_exceptions
async def fetch_l2_book(self: PerpMixin, coin: str) -> Book:
  raw = await self.shared.client.info.l2_book(coin)
  bids_raw, asks_raw = raw['levels']
  return Book(
    bids=[Book.Entry(price=Decimal(b['px']), qty=Decimal(b['sz'])) for b in bids_raw[:1]],
    asks=[Book.Entry(price=Decimal(a['px']), qty=Decimal(a['sz'])) for a in asks_raw[:1]],
  )


@wrap_exceptions
async def perp_tickers(
  self: PerpMixin, markets: Collection[str] | None = None,
) -> Mapping[str, Ticker]:
  """Fetch ticker snapshots for the whole perp universe in one call.

  Args:
    markets: Asset names to keep. `None` keeps the whole universe.

  Returns:
    A mapping of asset name to its `Ticker`.
  """
  _, perp_meta, asset_ctxs = await self.shared.load_perp_meta_for_dex(self.dex_name, refetch=True)
  wanted = None if markets is None else set(markets)

  result: dict[str, Ticker] = {}
  for asset, ctx in zip(perp_meta['universe'], asset_ctxs):
    name = asset['name']
    if wanted is not None and name not in wanted:
      continue
    result[name] = Ticker(
      last=Decimal(px) if (px := ctx.get('midPx')) is not None else None,
      base_volume_24h=Decimal(ctx['dayNtlVlm']),
    )

  if wanted is not None and (missing := wanted - set(result)):
    raise ValueError(f'Perps not found: {", ".join(sorted(missing))}')

  sem = asyncio.Semaphore(20)

  async def _enrich(coin: str) -> None:
    async with sem:
      try:
        book = await fetch_l2_book(self, coin)
        bbo = ticker_from_book(book)
        t = result[coin]
        t.bid, t.ask = bbo.bid, bbo.ask
        t.bid_qty, t.ask_qty = bbo.bid_qty, bbo.ask_qty
      except Exception:
        ...

  await asyncio.gather(*(_enrich(name) for name in result))
  return result
