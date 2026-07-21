"""Tests for the bulk `perp_stats`/`tickers` interface and its venue overrides."""

from typing_extensions import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from tribulnation.sdk.market import Book, NextFunding, PerpExchange, PerpMarket
from tribulnation.sdk.market.exchange import ticker_from_book

INDEX_TOLERANCE = Decimal('0.01')
"""Relative index-price drift allowed between the bulk call and a per-market call."""
FUNDING_TOLERANCE = Decimal('0.001')
"""Absolute funding-rate drift allowed between the bulk call and a per-market call."""

@dataclass
class FakePerpMarket(PerpMarket):
  """A perp market that serves canned index/funding/book data."""
  name: str
  price: Decimal
  calls: list[str] = field(default_factory=list)

  async def index(self, *, settings={}) -> Decimal:
    """Return the canned index price."""
    self.calls.append(f'index:{self.name}')
    return self.price

  async def next_funding(self) -> NextFunding:
    """Return a canned next-funding entry."""
    self.calls.append(f'next_funding:{self.name}')
    return NextFunding(
      rate=Decimal('0.0001'),
      time=datetime(2026, 1, 1).astimezone(),
      interval=timedelta(hours=1),
    )

  async def depth(self, *, levels: int | None = None) -> Book:
    """Return a canned one-level book around the canned price."""
    self.calls.append(f'depth:{self.name}')
    return Book(
      bids=[Book.Entry(self.price - 1, Decimal(2))],
      asks=[Book.Entry(self.price + 1, Decimal(3))],
    )

@dataclass
class FakePerpExchange(PerpExchange):
  """An exchange with no bulk endpoint, exercising the SDK's default fan-out."""
  markets_: dict[str, FakePerpMarket]

  async def markets(self) -> Sequence[str]:
    """List the canned market IDs."""
    return list(self.markets_)

  async def market(self, market_id: str, /) -> FakePerpMarket:
    """Fetch a canned market by ID."""
    return self.markets_[market_id]

def _fake_exchange() -> FakePerpExchange:
  """Build a two-market fake exchange."""
  return FakePerpExchange(markets_={
    'BTC': FakePerpMarket(name='BTC', price=Decimal(100_000)),
    'ETH': FakePerpMarket(name='ETH', price=Decimal(4_000)),
  })

async def test_base_perp_stats_raises() -> None:
  """The base `perp_stats` raises when the venue doesn't override it."""
  exchange = _fake_exchange()
  with pytest.raises(NotImplementedError):
    await exchange.perp_stats()

async def test_base_tickers_raises() -> None:
  """The base `tickers` raises when the venue doesn't override it."""
  exchange = _fake_exchange()
  with pytest.raises(NotImplementedError):
    await exchange.tickers()

def test_ticker_from_empty_book() -> None:
  """An empty book yields an all-`None` ticker rather than raising."""
  ticker = ticker_from_book(Book())
  assert ticker.bid is None and ticker.ask is None
  assert ticker.bid_qty is None and ticker.ask_qty is None

async def assert_bulk_agrees(exchange: PerpExchange, market_ids: Sequence[str]) -> None:
  """Check a venue's bulk `perp_stats` against its per-market index/funding calls."""
  all_stats = await exchange.perp_stats()
  assert len(all_stats) > len(market_ids)
  assert set(market_ids) <= set(all_stats)

  stats = await exchange.perp_stats(market_ids)
  assert set(stats) == set(market_ids)

  for market_id in market_ids:
    entry = stats[market_id]
    market = await exchange.market(market_id)
    index = await market.index()
    funding = await market.next_funding()

    assert entry.index > 0
    assert abs(entry.index - index) <= index * INDEX_TOLERANCE, market_id
    assert entry.funding is not None
    assert abs(entry.funding - funding.rate) <= FUNDING_TOLERANCE, market_id
    assert entry.funding_interval == funding.interval, market_id
    assert entry.next_funding_time == funding.time, market_id

@pytest.mark.live
async def test_hyperliquid_perp_stats_bulk() -> None:
  """Hyperliquid's one-call `perp_stats` agrees with its per-market values."""
  from tribulnation.hyperliquid import HyperliquidMarket
  venue = HyperliquidMarket.http('0x0000000000000000000000000000000000000000')
  async with venue:
    exchange = await venue.perp_exchange('')
    await assert_bulk_agrees(exchange, ['BTC', 'ETH'])
    stats = await exchange.perp_stats(['BTC'])
    assert stats['BTC'].mark is not None
    assert stats['BTC'].open_interest is not None

@pytest.mark.live
async def test_dydx_perp_stats_bulk() -> None:
  """dYdX's one-call `perp_stats` agrees with its per-market values."""
  from tribulnation.dydx import DydxMarket
  venue = DydxMarket.new(address='dydx1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq')
  async with venue:
    exchange = await venue.perp_exchange('perp')
    await assert_bulk_agrees(exchange, ['BTC-USD', 'ETH-USD'])
    stats = await exchange.perp_stats(['BTC-USD'])
    assert stats['BTC-USD'].mark is None
    assert stats['BTC-USD'].open_interest is not None
