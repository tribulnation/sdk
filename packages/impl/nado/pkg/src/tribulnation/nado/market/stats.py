"""Tickers, perpetual stats, next funding and the index price.

Funding settles hourly, on the hour, and Nado quotes every rate (`funding_rate_x18`,
`premium_x18`) as its 24-hour equivalent, positive when longs pay ("Funding Rates",
docs.nado.xyz, read 2026-11-17). The SDK's rates are per settlement, so they are the
venue's divided by 24.
"""

from datetime import datetime, timedelta
from decimal import Decimal
import asyncio

from typing_extensions import Collection, Mapping
import typed_nado.archive_v2.tickers
from typed_nado import schemas
from typed_nado.schemas import MarketPrice
from tribulnation.sdk.core import MissingData
from tribulnation.sdk.market import NextFunding, PerpStats, Ticker

from ..core import ProductType, Shared, x18

FUNDING_INTERVAL = timedelta(hours=1)
"""Funding settles every hour, on the hour."""
DAY_INTERVALS = Decimal(24)
"""Settlements per day: the venue's 24-hour rates over this are per settlement."""


def decimal(value: float) -> Decimal:
  """A REST v2 float as the decimal it was sent as (its shortest repr)."""
  return Decimal(repr(value))


def side(price_x18: int) -> Decimal | None:
  """A best bid or ask, `None` where the side is empty (`0`)."""
  return x18(price_x18) if int(price_x18) > 0 else None


def per_interval(rate_x18: int) -> Decimal:
  """A 24-hour-equivalent rate as the rate of one hourly settlement."""
  return x18(rate_x18) / DAY_INTERVALS


def next_hour(time: datetime) -> datetime:
  """The first settlement after `time`: the next full hour."""
  return time.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL


async def selected(
  shared: Shared, markets: Collection[str] | None, type: ProductType
) -> dict[str, int]:
  """Product ids by symbol: every product of `type` when `markets` is `None`, else the
  named ones Nado lists as that type."""
  listed = await shared.listed(type)
  names = listed if markets is None else [m for m in markets if m in listed]
  return {name: shared.symbols[name]['product_id'] for name in names}


def parse_ticker(
  t: typed_nado.archive_v2.tickers.Ticker | None, price: MarketPrice | None
) -> Ticker:
  """Last price and 24h volumes from the archive's ticker, best bid and ask from the
  gateway; Nado publishes no best-level sizes without a book request per market."""
  return Ticker(
    last=decimal(t['last_price']) if t is not None else None,
    bid=side(price['bid_x18']) if price is not None else None,
    ask=side(price['ask_x18']) if price is not None else None,
    base_volume_24h=decimal(t['base_volume']) if t is not None else None,
    quote_volume_24h=decimal(t['quote_volume']) if t is not None else None,
  )


async def tickers(
  shared: Shared, markets: Collection[str] | None, *, type: ProductType
) -> Mapping[str, Ticker]:
  """Tickers of the requested products of one type: one archive `tickers` and one
  gateway `market_prices` request.

  The archive sends prices and volumes as JSON floats, which typed-nado declares
  `float`; they are read back through their shortest repr, the number as sent.
  """
  ids = await selected(shared, markets, type)
  if not ids:
    return {}
  rows, prices = await asyncio.gather(
    shared.call(lambda: shared.client.archive_v2.tickers(type)),
    shared.call(lambda: shared.client.gateway.market_prices(list(ids.values()))),
  )
  by_product = {t['product_id']: t for t in rows.values()}
  best = {p['product_id']: p for p in prices['market_prices']}
  return {
    name: parse_ticker(by_product.get(pid), best.get(pid)) for name, pid in ids.items()
  }


async def perp_stats(
  shared: Shared, markets: Collection[str] | None
) -> Mapping[str, PerpStats]:
  """Index and mark (`perp_prices`), the current interval's indicative funding
  (`funding_rates`) and base-unit open interest (`all_products`), three requests for
  every perpetual.

  Reading every market leaves out one Nado publishes no prices for (an untradable
  one), while a named one raises.

  Raises:
    MissingData: A named market has no index price.
  """

  ids = await selected(shared, markets, 'perp')
  if not ids:
    return {}
  product_ids = list(ids.values())
  prices, rates, products = await asyncio.gather(
    shared.call(lambda: shared.client.archive.perp_prices(product_ids)),
    shared.call(lambda: shared.client.archive.funding_rates(product_ids)),
    shared.call(shared.client.gateway.all_products),
  )
  interest = {
    p['product_id']: x18(p['state']['open_interest']) for p in products['perp_products']
  }
  stats: dict[str, PerpStats] = {}
  for name, pid in ids.items():
    price = prices.get(str(pid))
    if price is None:
      if markets is None:
        continue
      raise MissingData(
        f'Nado sent no index price for {name}', market_id=name, field='index'
      )
    rate = rates.get(str(pid))
    stats[name] = PerpStats(
      index=x18(price['index_price_x18']),
      mark=x18(price['mark_price_x18']),
      funding=per_interval(rate['funding_rate_x18']) if rate is not None else None,
      next_funding_time=next_hour(rate['update_time']) if rate is not None else None,
      funding_interval=FUNDING_INTERVAL,
      open_interest=interest.get(pid),
    )
  return stats


def parse_next_funding(rate: schemas.FundingRate) -> NextFunding:
  """The indicative rate of the settlement after `update_time`, with its premium."""
  premium = rate.get('premium_x18')
  return NextFunding(
    rate=per_interval(rate['funding_rate_x18']),
    time=next_hour(rate['update_time']),
    interval=FUNDING_INTERVAL,
    premium=per_interval(premium) if premium is not None else None,
  )


async def next_funding(shared: Shared, product_id: int) -> NextFunding:
  """The archive's latest predicted rate (recomputed about every 20 s)."""
  rate = await shared.call(lambda: shared.client.archive.funding_rate(product_id))
  return parse_next_funding(rate)


async def index(shared: Shared, product_id: int) -> Decimal:
  """The archive's latest index price."""
  price = await shared.call(lambda: shared.client.archive.price(product_id))
  return x18(price['index_price_x18'])
