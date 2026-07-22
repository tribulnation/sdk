import asyncio
import logging

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk import SDK
from tribulnation.sdk.market import Book, Exchange as _Exchange, Settings, Ticker
from tribulnation.sdk.market.exchange import ticker_from_book

from tribulnation.hyperliquid.core import wrap_exceptions
from .impl import SpotMixin
from .spot_market import SpotMarket


def _market_id(base: str, quote: str, asset_idx: int) -> str:
  return f'{base}/{quote}:{asset_idx}'


def parse_market_id(market_id: str) -> tuple[str, str, int]:
  """Parse canonical spot `market_id` format: `BASE/QUOTE:ASSET_IDX`."""
  ticker, idx_str = market_id.rsplit(':', 1)
  base, quote = ticker.split('/', 1)
  return base, quote, int(idx_str)


@SDK.method
@wrap_exceptions
async def fetch_l2_book(self: SpotMixin, coin: str) -> Book:
  raw = await self.shared.client.info.l2_book(coin)
  bids_raw, asks_raw = raw['levels']
  return Book(
    bids=[Book.Entry(price=Decimal(b['px']), qty=Decimal(b['sz'])) for b in bids_raw[:1]],
    asks=[Book.Entry(price=Decimal(a['px']), qty=Decimal(a['sz'])) for a in asks_raw[:1]],
  )


@dataclass(frozen=True, kw_only=True)
class SpotExchange(SpotMixin, _Exchange):

  @property
  def venue_id(self) -> str:
    return 'hyperliquid'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    meta = await self.shared.load_spot_meta()
    out: list[str] = []
    for asset in meta['universe']:
      spot_index = asset['index']
      m = await self.shared.spot_meta_of(spot_index)
      out.append(_market_id(m['base_meta']['name'], m['quote_meta']['name'], spot_index))
    return out

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch spot tickers, optionally enriched with per-market order books.

    `hyperliquid.tickers_fetch_depth` controls whether order books are fetched
    (default `True`), and `hyperliquid.tickers_depth_concurrent` controls their
    concurrency (default 20).
    """
    spot_meta, asset_ctxs = await self.shared.client.info.spot_meta_and_asset_ctxs()
    tokens_by_index = {t['index']: t for t in spot_meta['tokens']}
    wanted = None if markets is None else set(markets)

    result: dict[str, Ticker] = {}
    coin_to_market: dict[str, str] = {}
    for asset, ctx in zip(spot_meta['universe'], asset_ctxs):
      spot_index = asset['index']
      base_idx, quote_idx = asset['tokens']
      base_name = tokens_by_index[base_idx]['name']
      quote_name = tokens_by_index[quote_idx]['name']
      mid = _market_id(base_name, quote_name, spot_index)
      if wanted is not None and mid not in wanted:
        continue
      result[mid] = Ticker(
        last=Decimal(px) if (px := ctx.get('midPx')) is not None else None,
        base_volume_24h=Decimal(ctx['dayNtlVlm']),
      )
      coin_to_market[asset['name']] = mid

    if wanted is not None and (missing := wanted - set(result)):
      raise ValueError(f'Spot markets not found: {", ".join(sorted(missing))}')

    venue_settings = settings.get('hyperliquid', {})
    if not venue_settings.get('tickers_fetch_depth', True):
      return result

    concurrency = venue_settings.get('tickers_depth_concurrent', 20)
    sem = asyncio.Semaphore(concurrency)

    async def _enrich(coin: str, market_id: str) -> None:
      async with sem:
        try:
          book = await fetch_l2_book(self, coin)
          bbo = ticker_from_book(book)
          t = result[market_id]
          t.bid, t.ask = bbo.bid, bbo.ask
          t.bid_qty, t.ask_qty = bbo.bid_qty, bbo.ask_qty
        except Exception as exc:
          logging.warning('tickers: %s book fetch failed: %s', coin, exc)

    await asyncio.gather(*(_enrich(c, m) for c, m in coin_to_market.items()))
    return result

  async def market(self, market_id: str, /):
    base, quote, spot_index = parse_market_id(market_id)
    meta = await self.shared.spot_meta_of(spot_index)
    if meta['base_meta']['name'] != base or meta['quote_meta']['name'] != quote:
      raise ValueError(
        f"Spot market_id mismatch for idx={spot_index}: expected {base}/{quote}, got {meta['base_meta']['name']}/{meta['quote_meta']['name']}"
      )
    return SpotMarket(shared=self.shared, meta=meta)
