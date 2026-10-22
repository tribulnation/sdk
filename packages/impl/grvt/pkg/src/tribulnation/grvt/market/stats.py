"""Tickers, perpetual stats, next funding and the index price.

GRVT has no bulk ticker: one `ticker` per instrument, sent concurrently over the
market-data WebSocket.
"""

from datetime import timedelta
from decimal import Decimal
import asyncio

from typing_extensions import Collection, Literal, Mapping
from typed_grvt.schemas import InstrumentDisplay, Ticker as GrvtTicker
from tribulnation.sdk.core import MissingData
from tribulnation.sdk.market import NextFunding, PerpStats, Ticker

from ..core import Shared, percent


def price_or_none(value: Decimal | None) -> Decimal | None:
  """A ticker price, or `None` where the venue sends `0` (an empty side) or nothing."""
  return value if value else None


def volume(buy: Decimal | None, sell: Decimal | None) -> Decimal | None:
  """Taker buy plus taker sell volume (each trade has one taker), or `None` if either is
  missing."""
  return None if buy is None or sell is None else buy + sell


def parse_ticker(t: GrvtTicker) -> Ticker:
  """Last price, best bid/ask with sizes and 24h volumes; empty sides are `None`."""
  bid = price_or_none(t.get('best_bid_price'))
  ask = price_or_none(t.get('best_ask_price'))
  return Ticker(
    last=price_or_none(t.get('last_price')),
    bid=bid,
    ask=ask,
    bid_qty=t.get('best_bid_size') if bid is not None else None,
    ask_qty=t.get('best_ask_size') if ask is not None else None,
    base_volume_24h=volume(t.get('buy_volume_24h_b'), t.get('sell_volume_24h_b')),
    quote_volume_24h=volume(t.get('buy_volume_24h_q'), t.get('sell_volume_24h_q')),
  )


def interval_of(instrument: InstrumentDisplay) -> timedelta | None:
  """The funding interval: the instrument's `funding_interval_hours` (8 or 4); the
  ticker does not send its own."""
  hours = instrument.get('funding_interval_hours')
  return timedelta(hours=hours) if hours else None


async def ticker(
  shared: Shared, instrument: str, *, transport: Literal['http', 'ws'] = 'http'
) -> GrvtTicker:
  """One venue ticker."""
  return await shared.call(
    lambda: shared.client.market.ticker(instrument, transport=transport)
  )


async def venue_tickers(
  shared: Shared, markets: Collection[str] | None
) -> dict[str, GrvtTicker]:
  """The venue tickers of the requested perpetuals (every one when `None`), fetched
  concurrently; names GRVT does not list are left out."""
  instruments = await shared.load_instruments()
  names = (
    list(instruments) if markets is None else [m for m in markets if m in instruments]
  )
  rows = await asyncio.gather(*(ticker(shared, name, transport='ws') for name in names))
  return dict(zip(names, rows))


async def tickers(
  shared: Shared, markets: Collection[str] | None
) -> Mapping[str, Ticker]:
  """Tickers of the requested perpetuals."""
  return {m: parse_ticker(t) for m, t in (await venue_tickers(shared, markets)).items()}


def missing_index(instrument: str) -> MissingData:
  """The error for a ticker or mini ticker without its index price."""
  return MissingData(
    f'GRVT sent no index price for {instrument}', market_id=instrument, field='index'
  )


async def perp_stats(
  shared: Shared, markets: Collection[str] | None
) -> Mapping[str, PerpStats]:
  """Index, mark, indicative funding and base-unit open interest per perpetual.

  As for MEXC (ADR 0030), reading every market leaves out one whose ticker has no index
  price, while a named one raises.

  Raises:
    MissingData: A named market's ticker has no index price.
  """
  rows = await venue_tickers(shared, markets)
  stats: dict[str, PerpStats] = {}
  for name, t in rows.items():
    index = t.get('index_price')
    if index is None:
      if markets is None:
        continue
      raise missing_index(name)
    rate = t.get('funding_rate')
    stats[name] = PerpStats(
      index=index,
      mark=t.get('mark_price'),
      funding=None if rate is None else percent(rate),
      next_funding_time=t.get('next_funding_time'),
      funding_interval=interval_of(shared.instruments[name]),
      open_interest=t.get('open_interest'),
    )
  return stats


async def next_funding(shared: Shared, instrument: str) -> NextFunding:
  """The indicative rate of the interval ending at `next_funding_time`.

  The ticker's `funding_rate` is in percentage points (not the centibeeps GRVT
  documents), positive when longs pay. No premium is published.

  Raises:
    MissingData: The ticker or instrument omits the rate, the time or the interval.
  """
  detail, t = await asyncio.gather(
    shared.instrument(instrument), ticker(shared, instrument)
  )
  rate, time = t.get('funding_rate'), t.get('next_funding_time')
  interval = interval_of(detail)
  if rate is None or time is None or interval is None:
    field = 'rate' if rate is None else 'time' if time is None else 'interval'
    raise MissingData(
      f'GRVT sent no funding {field} for {instrument}',
      market_id=instrument,
      field=field,
    )
  return NextFunding(rate=percent(rate), time=time, interval=interval)


async def index(shared: Shared, instrument: str) -> Decimal:
  """The mini ticker's `index_price`.

  Raises:
    MissingData: The mini ticker omits it.
  """
  mini = await shared.call(lambda: shared.client.market.mini_ticker(instrument))
  price = mini.get('index_price')
  if price is None:
    raise missing_index(instrument)
  return price
