"""Request shapes of the paged reads, their bounds, and page retries."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from typing_extensions import Any

import pytest
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError
from typed_extended import Extended

from tribulnation.extended.core import Shared
from tribulnation.extended.market import history
from tribulnation.sdk import Context, NetworkError
from tribulnation.sdk.market import ExchangeFundingPayment, ExchangeTrade

HOUR = timedelta(hours=1)
END = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def row(name: str, kind: str = 'PERPETUAL', **extra: Any) -> Any:
  """A cached market row with what the history paths read."""
  return {'name': name, 'type': kind, 'collateralAssetName': 'USD', **extra}


@pytest.fixture
async def shared():
  """A shared owner around a credential-free client; endpoints are replaced per test."""
  async with Extended.new(public=True) as client:
    out = Shared(client=client)
    out.markets.update(
      {
        'BTC-USD': row('BTC-USD', createdAt=END - 5 * HOUR),
        'OLD-USD': row('OLD-USD', status='DELISTED'),
        'BTCSPOT-USD': row('BTCSPOT-USD', 'SPOT'),
      }
    )
    yield out


def candle(t: datetime) -> dict[str, Any]:
  """A trade candle opening at `t`."""
  return {
    'T': t,
    'o': Decimal(1),
    'h': Decimal(2),
    'l': Decimal(1),
    'c': Decimal(2),
    'v': Decimal(3),
  }


async def test_candles_walk_back_from_end_and_retry(shared: Shared):
  """The walk asks for the window's opens (capped at 1000) before `end`, stops once a
  page reaches the window's first open, drops older rows, and retries a failed page."""
  seen: dict[str, Any] = {}
  calls: list[int] = []
  start = END - 1500 * HOUR + timedelta(minutes=30)

  async def fetch(state: int) -> tuple[list[dict[str, Any]], int | None]:
    """Pages of 1000 hourly candles, newest first; the second fails once."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    top = END - state * 1000 * HOUR
    return [candle(top - (i + 1) * HOUR) for i in range(1000)], state + 1

  def candles_paged(market: str, **kwargs: Any) -> PaginatedResponse[Any, int]:
    """Record the walk's request and serve the fixture pages."""
    seen.update(kwargs, market=market)
    return PaginatedResponse(0, fetch)

  shared.client.info.candles_paged = candles_paged  # type: ignore[method-assign]
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    pages = [p async for p in history.candles(shared, 'BTC-USD', '1h', start, END)]
  assert seen == {
    'market': 'BTC-USD',
    'candle_type': 'trades',
    'interval': 'PT1H',
    'limit': 1000,
    'end_time': END,
  }
  assert calls == [0, 1, 1]
  opens = [c.time for page in pages for c in page]
  assert [len(page) for page in pages] == [1000, 499]
  assert opens[0] == END - HOUR and opens[-1] == END - 1499 * HOUR
  assert len(set(opens)) == len(opens) and all(start <= t < END for t in opens)


async def test_candles_of_a_short_window_ask_for_its_opens(shared: Shared):
  """A window shorter than one page asks for exactly its grid opens; an empty one
  makes no request."""
  limits: list[int] = []

  def candles_paged(market: str, **kwargs: Any) -> PaginatedResponse[Any, int]:
    """One page of the requested opens."""
    limits.append(kwargs['limit'])

    async def fetch(state: int) -> tuple[list[dict[str, Any]], None]:
      return [candle(END - (i + 1) * HOUR) for i in range(kwargs['limit'])], None

    return PaginatedResponse(0, fetch)

  shared.client.info.candles_paged = candles_paged  # type: ignore[method-assign]
  rows = [
    c
    async for p in history.candles(shared, 'BTC-USD', '1h', END - 3 * HOUR, END)
    for c in p
  ]
  assert limits == [3] and len(rows) == 3
  assert [p async for p in history.candles(shared, 'BTC-USD', '1h', END, END)] == []
  assert limits == [3]


async def test_funding_rates_default_to_the_market_creation(shared: Shared):
  """An open start reads the market's `createdAt`; rates keep their sign."""
  seen: dict[str, Any] = {}

  def funding_rates_paged(market: str, **kwargs: Any) -> PaginatedResponse[Any, int]:
    """One page of two rates."""
    seen.update(kwargs)

    async def fetch(state: int) -> tuple[list[dict[str, Any]], None]:
      return [
        {'m': market, 'T': END, 'f': Decimal('0.000013')},
        {'m': market, 'T': END - HOUR, 'f': Decimal('-0.00002')},
      ], None

    return PaginatedResponse(0, fetch)

  shared.client.info.funding_rates_paged = funding_rates_paged  # type: ignore[method-assign]
  rates = [
    r async for p in history.funding_rates(shared, 'BTC-USD', None, END) for r in p
  ]
  assert seen == {'start_time': END - 5 * HOUR, 'end_time': END}
  assert [(r.time, r.rate) for r in rates] == [
    (END, Decimal('0.000013')),
    (END - HOUR, Decimal('-0.00002')),
  ]


def fill(i: int, market: str = 'BTC-USD', **extra: Any) -> dict[str, Any]:
  """A buy fill `i` hours before `END`."""
  return {
    'id': i,
    'accountId': 3880,
    'market': market,
    'orderId': 100 + i,
    'externalOrderId': f'cid-{i}',
    'side': 'BUY',
    'price': Decimal('80000'),
    'qty': Decimal('0.01'),
    'value': Decimal('800'),
    'fee': Decimal('0.2'),
    'tradeType': 'TRADE',
    'createdTime': END - i * HOUR,
    'isTaker': True,
    **extra,
  }


async def test_trades_history_retries_and_stops_at_start(shared: Shared):
  """A failed later page is fetched again; rows newer than `end` are skipped, paging
  stops at the first fill before `start`, and exchange-wide rows leave spot out."""
  calls: list[int] = []
  seen: dict[str, Any] = {}
  pages = [
    [fill(0), fill(1, 'BTCSPOT-USD')],
    [fill(2, 'OLD-USD'), fill(3, 'NEW-USD')],
    [fill(4), fill(9)],
    [fill(10)],
  ]

  async def fetch(state: int) -> tuple[list[dict[str, Any]], int | None]:
    """The fixture pages; page two fails once."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    return pages[state], state + 1 if state + 1 < len(pages) else None

  def trades_paged(market: Any = None, **kwargs: Any) -> PaginatedResponse[Any, int]:
    """Record the query and serve the fixture pages."""
    seen.update(kwargs, market=market)
    return PaginatedResponse(0, fetch)

  shared.client.account.trades_paged = trades_paged  # type: ignore[method-assign]
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    rows = [
      t
      async for p in history.trades_history(
        shared, None, END - 5 * HOUR, END - HOUR / 2
      )
      for t in p
    ]
  assert calls == [0, 1, 1, 2]
  assert seen == {'market': None, 'limit': 100}
  assert [t.id for t in rows] == ['2', '3', '4']
  assert all(isinstance(t, ExchangeTrade) for t in rows)
  assert [getattr(t, 'market_id') for t in rows] == ['OLD-USD', 'NEW-USD', 'BTC-USD']
  first = rows[0]
  assert (first.order_id, first.client_order_id, first.qty, first.maker) == (
    '102',
    'cid-2',
    Decimal('0.01'),
    False,
  )
  assert first.fee is not None and first.fee.asset == 'USD'


async def test_market_trades_history_filters_by_market(shared: Shared):
  """A market's history asks the venue for that market and yields plain `Trade`s."""
  seen: dict[str, Any] = {}

  def trades_paged(market: Any = None, **kwargs: Any) -> PaginatedResponse[Any, int]:
    """One page of one sell."""
    seen['market'] = market

    async def fetch(state: int) -> tuple[list[dict[str, Any]], None]:
      return [fill(1, side='SELL', isTaker=False)], None

    return PaginatedResponse(0, fetch)

  shared.client.account.trades_paged = trades_paged  # type: ignore[method-assign]
  rows = [
    t
    async for p in history.trades_history(shared, 'BTC-USD', END - 2 * HOUR, END)
    for t in p
  ]
  assert seen == {'market': ['BTC-USD']}
  assert len(rows) == 1 and not isinstance(rows[0], ExchangeTrade)
  assert rows[0].qty == Decimal('-0.01') and rows[0].maker


def payment(id: int, market: str, paid: datetime, fee: str, side: str) -> Any:
  """A funding payment row; `fee` is the venue's `fundingFee`."""
  return {
    'id': id,
    'accountId': 3880,
    'market': market,
    'positionId': 900 + id,
    'side': side,
    'size': Decimal('1000'),
    'value': Decimal('3.07'),
    'markPrice': Decimal('0.00307'),
    'fundingFee': Decimal(fee),
    'fundingRate': Decimal('0.000013'),
    'paidTime': paid,
  }


async def test_funding_payments_are_signed_and_bounded(shared: Shared):
  """`fundingFee` is received-positive as the venue sends it (testnet: a long paying a
  positive rate read `-0.000041`, the short `0.00004`); payments after `end` are dropped
  and the exchange-wide form names each market, delisted included."""
  seen: dict[str, Any] = {}
  rows = [
    payment(1, 'BTC-USD', END - 3 * HOUR, '-0.000041', 'LONG'),
    payment(2, 'OLD-USD', END - 2 * HOUR, '0.00004', 'SHORT'),
    payment(3, 'BTC-USD', END + HOUR, '-0.000041', 'LONG'),
  ]

  def funding_history_paged(
    market: Any = None, **kwargs: Any
  ) -> PaginatedResponse[Any, int]:
    """Record the query and serve the rows in two pages."""
    seen.update(kwargs, market=market)

    async def fetch(state: int) -> tuple[list[Any], int | None]:
      return ([rows[0]], 1) if state == 0 else (rows[1:], None)

    return PaginatedResponse(0, fetch)

  shared.client.account.funding_history_paged = funding_history_paged  # type: ignore[method-assign]
  every = [
    p
    async for page in history.funding_payments(shared, None, END - 5 * HOUR, END)
    for p in page
  ]
  assert seen == {'market': None, 'start_time': END - 5 * HOUR}
  assert [(getattr(p, 'market_id'), p.amount, p.time) for p in every] == [
    ('BTC-USD', Decimal('-0.000041'), END - 3 * HOUR),
    ('OLD-USD', Decimal('0.00004'), END - 2 * HOUR),
  ]
  assert all(isinstance(p, ExchangeFundingPayment) for p in every)
  one = [
    p
    async for page in history.funding_payments(shared, 'BTC-USD', END - 5 * HOUR, END)
    for p in page
  ]
  assert seen['market'] == ['BTC-USD']
  assert not isinstance(one[0], ExchangeFundingPayment)
  with pytest.raises(ValueError, match='timezone'):
    [p async for p in history.funding_payments(shared, None, datetime(2026, 1, 1), END)]
