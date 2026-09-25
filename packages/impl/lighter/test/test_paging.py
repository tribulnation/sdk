"""Request shapes of the paged reads, and page retries at the request boundary."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any

import pytest
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError
from typed_lighter import Lighter

from tribulnation.lighter.core import Shared
from tribulnation.lighter.market import history
from tribulnation.sdk import Context, NetworkError

HOUR = timedelta(hours=1)
END = datetime(2026, 9, 24, 15, tzinfo=timezone.utc)


class AccountShared(Shared):
  """A public client posing as account 476."""

  @property
  def account_index(self) -> int:
    """The fixture account."""
    return 476


@pytest.fixture
async def shared():
  """A shared owner around a credential-free client; endpoints are replaced per test."""
  async with Lighter.new(public=True) as client:
    yield AccountShared(client=client)


async def test_candle_windows_carry_their_own_count_back(shared: Shared):
  """The CDN keys `candles` on end and `count_back`, not start: each window's
  `count_back` is its own number of grid opens, so no two windows share a key."""
  requests: list[dict[str, Any]] = []

  async def candles(**kwargs: Any) -> dict[str, Any]:
    """Serve one row per hour of the window, plus one extended row before it."""
    requests.append(kwargs)
    start, end = kwargs['start_timestamp'], kwargs['end_timestamp']
    hours = int((end - start) / HOUR)
    times = [start - HOUR] + [start + i * HOUR for i in range(hours)]
    return {'c': [{'t': t, 'o': 1.0, 'h': 1.0, 'l': 1.0, 'c': 1.0} for t in times]}

  shared.client.api.markets.candles = candles  # type: ignore[method-assign]
  start = END - 550 * HOUR + timedelta(minutes=30)
  pages = [page async for page in history.candles(shared, 1, '1h', start, END)]
  assert [(r['start_timestamp'], r['count_back']) for r in requests] == [
    (END - 549 * HOUR, 499),
    (END - 50 * HOUR, 50),
  ]
  opens = [c.time for page in pages for c in page]
  assert opens == [END - i * HOUR for i in range(549, 0, -1)]
  assert all(c.volume == 0 for page in pages for c in page)


async def test_trade_pages_retry_without_duplicates(shared: Shared):
  """A failed later page is fetched again under an SDK retry, and rows appear once."""
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[dict[str, Any]], int | None]:
    """One trade per page; page two fails once."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    row: dict[str, Any] = {
      'trade_id_str': str(state),
      'market_id': 4095,
      'timestamp': END - state * HOUR,
      'size': Decimal(1),
      'price': Decimal(1),
      'usd_amount': Decimal(1),
      'ask_account_id': 1,
      'bid_account_id': 476,
      'is_maker_ask': True,
      'taker_fee': 280,
    }
    return [row], state + 1 if state < 2 else None

  def trades_paged(*args: Any, **kwargs: Any) -> PaginatedResponse[Any, int]:
    """Walk the fixture pages."""
    return PaginatedResponse(0, fetch)

  shared.client.api.account.orders.trades_paged = trades_paged  # type: ignore[method-assign]
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    pages = [
      page
      async for page in history.trades_history(
        shared, 'perp', None, END - 10 * HOUR, END, fee=history.perp_fee
      )
    ]
  assert calls == [0, 1, 1, 2]
  assert [t.id for page in pages for t in page] == ['0', '1', '2']
  assert all(getattr(t, 'market_id') == '4095' for page in pages for t in page)


async def test_funding_rates_are_signed_and_inclusive(shared: Shared):
  """`direction` signs the unsigned percent rate; both bounds are inclusive."""
  seen: dict[str, Any] = {}

  def fundings_paged(**kwargs: Any) -> PaginatedResponse[Any, int]:
    """Three hourly settlements around the requested window."""
    seen.update(kwargs)
    rows: list[dict[str, Any]] = [
      {'timestamp': END - HOUR, 'rate': Decimal('0.0012'), 'direction': 'long'},
      {'timestamp': END, 'rate': Decimal('0.0019'), 'direction': 'short'},
      {'timestamp': END + HOUR, 'rate': Decimal('0.0001'), 'direction': 'long'},
    ]

    async def fetch(state: int) -> tuple[list[dict[str, Any]], None]:
      """One page."""
      return rows, None

    return PaginatedResponse(0, fetch)

  async def perp(market_id: int, *, refetch: bool = False):
    """Details are only read for an open start."""
    return {'created_at': END - 10 * HOUR}

  shared.client.api.markets.fundings_paged = fundings_paged  # type: ignore[method-assign]
  object.__setattr__(shared, 'perp', perp)
  rates = [
    r async for page in history.funding_rates(shared, 1, END - HOUR, END) for r in page
  ]
  assert [(r.time, r.rate) for r in rates] == [
    (END - HOUR, Decimal('0.000012')),
    (END, Decimal('-0.000019')),
  ]
  assert seen['start_timestamp'] == END - 3 * HOUR
  assert seen['count_back'] == 0


def test_stream_snapshots_accept_one_market_or_all():
  """A one-market frame is the stats themselves; `all` maps ids to stats."""
  from tribulnation.lighter.market.stats import selected

  assert selected(None, [0, 1]) == [0, 1]
  assert selected(['1', 'x', '7'], [0, 1]) == [1]
