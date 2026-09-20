"""Native linear perpetual discovery and public value conversions."""

from decimal import Decimal
from typing_extensions import Sequence, TypeGuard

from typed_kraken.futures.instruments import FuturesInstrument
from typed_kraken.futures.orderbook import FuturesOrderBook
from typed_kraken.schemas import FuturesMarketTicker, FuturesTicker
from tribulnation.sdk.market import Book, PerpStats, Rules, Ticker


def is_market_ticker(row: FuturesTicker) -> TypeGuard[FuturesMarketTicker]:
  """Separate market tickers from the index-only variant."""
  return 'tag' in row


def select_perps(
  instruments: Sequence[FuturesInstrument], tickers: Sequence[FuturesTicker]
) -> dict[str, FuturesInstrument]:
  """Select active non-tradfi USD linear perpetuals with one base unit per contract.

  The venue's non-tradfi classification includes some tokenized assets. Product
  identity comes from explicit instrument fields and ticker tags, never symbol text.
  """
  snapshots = {r['symbol']: r for r in tickers if is_market_ticker(r)}
  return {
    row['symbol']: row
    for row in instruments
    if row.get('type') == 'flexible_futures'
    and not row['tradfi']
    and not row['isExpired']
    and row['tradeable']
    and 'lastTradingTime' not in row
    and row.get('quote') == 'USD'
    and row.get('contractSize') == 1
    and (ticker := snapshots.get(row['symbol'])) is not None
    and ticker['tag'] == 'perpetual'
    and not ticker['suspended']
  }


def parse_ticker(row: FuturesMarketTicker) -> Ticker:
  """Preserve native base quantities and prices from a qualified linear contract."""
  return Ticker(
    last=Decimal(str(row['last'])) if 'last' in row else None,
    bid=Decimal(str(row['bid'])) if 'bid' in row else None,
    ask=Decimal(str(row['ask'])) if 'ask' in row else None,
    bid_qty=Decimal(str(row['bidSize'])) if 'bidSize' in row else None,
    ask_qty=Decimal(str(row['askSize'])) if 'askSize' in row else None,
    base_volume_24h=Decimal(str(row['vol24h'])),
    quote_volume_24h=Decimal(str(row['volumeQuote'])),
  )


def parse_stats(row: FuturesMarketTicker) -> PerpStats:
  """Preserve index, mark and base open interest; absolute funding is not relative."""
  return PerpStats(
    index=Decimal(str(row['indexPrice'])),
    mark=Decimal(str(row['markPrice'])),
    open_interest=Decimal(str(row['openInterest'])),
  )


def parse_book(row: FuturesOrderBook, *, levels: int | None) -> Book:
  """Sort the full native book before taking the best requested levels."""
  if levels is not None and levels < 1:
    raise ValueError('levels must be positive')
  book = Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in row['bids']],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in row['asks']],
  )
  return Book(bids=book.bids[:levels], asks=book.asks[:levels])


def parse_rules(row: FuturesInstrument, *, fee_asset: str) -> Rules:
  """Use native precision without treating maximum position size as an order cap."""
  precision = row.get('contractValueTradePrecision')
  tick = row.get('tickSize')
  if precision is None or int(precision) != precision or tick is None or tick <= 0:
    raise ValueError('Kraken instrument is missing valid price or quantity precision')
  step = Decimal(10) ** -int(precision)
  return Rules(
    fee_asset=fee_asset,
    tick_size=Decimal(str(tick)),
    step_size=step,
    fixed_min_qty=step,
    api=row['tradeable'] and not row['isExpired'],
    details=row,
  )
