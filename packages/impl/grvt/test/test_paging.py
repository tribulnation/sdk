"""Request bounds, local filtering, units and page retries of the history reads."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from typing_extensions import Any, Callable, Sequence, cast
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError
from typed_grvt.schemas import Fill

from tribulnation.grvt.core import Shared
from tribulnation.grvt.market import history
from tribulnation.sdk import AuthError, Context, NetworkError
from tribulnation.sdk.market import ExchangeFundingPayment, ExchangeTrade

BTC = 'BTC_USDT_Perp'
HOUR = timedelta(hours=1)
MICRO = timedelta(microseconds=1)
END = datetime(2026, 10, 22, 16, tzinfo=timezone.utc)


def pager(
  pages: Sequence[Sequence[Any]], calls: list[int], *, fail_at: int | None = None
) -> PaginatedResponse[Any, int]:
  """A walk over fixed pages, logging each page fetched; `fail_at` fails once."""

  async def fetch(state: int) -> tuple[Sequence[Any], int | None]:
    """One page; the walk ends after the last."""
    calls.append(state)
    if state == fail_at and calls.count(state) == 1:
      raise ClientNetworkError('disconnected')
    return pages[state], state + 1 if state + 1 < len(pages) else None

  return PaginatedResponse(0, fetch)


def recorder(
  pages: Sequence[Sequence[Any]], requests: list[dict[str, Any]], calls: list[int]
) -> Callable[..., PaginatedResponse[Any, int]]:
  """A `*_paged` endpoint recording its keyword arguments."""

  def paged(*args: Any, **kwargs: Any) -> PaginatedResponse[Any, int]:
    """Record the request, then walk the pages."""
    requests.append(kwargs)
    return pager(pages, calls)

  return paged


def fill(time: datetime, **changes: object) -> Fill:
  """A testnet taker buy on BTC, as `fill_history` sent it, with `changes`."""
  row: dict[str, Any] = {
    'event_time': time,
    'sub_account_id': '1',
    'instrument': BTC,
    'is_buyer': True,
    'is_taker': True,
    'size': Decimal('0.002'),
    'price': Decimal('81835.0'),
    'index_price': Decimal('81840'),
    'interest_rate': Decimal(0),
    'realized_pnl': Decimal(0),
    'fee': Decimal('0.073651'),
    'fee_rate': Decimal('0.045'),
    'trade_id': f'{int(time.timestamp())}-1',
    'order_id': '0x0101',
    'venue': 'ORDERBOOK',
    'is_liquidation': False,
    'client_order_id': '9759235347865617030',
    'signer': '0x0',
    'is_rpi': False,
    'builder': '0x0000000000000000000000000000000000000000',
    'builder_fee_rate': Decimal(0),
    'builder_fee': Decimal(0),
    'fee_currency': 'USDT',
    'repayment_scenario': 'UNSPECIFIED',
  }
  return cast(Fill, {**row, **changes})


async def test_candles_drop_the_inclusive_venue_end(shared: Shared, fake: Any):
  """The venue includes a candle opening at `end`; the SDK's `end` is exclusive."""
  requests: list[dict[str, Any]] = []
  rows: list[dict[str, Any]] = [
    {
      'open_time': END - i * HOUR,
      'open': Decimal(1),
      'high': Decimal(2),
      'low': Decimal('0.5'),
      'close': Decimal(1),
      'volume_b': Decimal(3),
      'volume_q': Decimal(4),
      'trades': 5,
    }
    for i in range(4)
  ]
  fake.market.candlesticks_paged = recorder([rows], requests, [])
  pages = [p async for p in history.candles(shared, BTC, '1h', END - 3 * HOUR, END)]
  assert [c.time for p in pages for c in p] == [
    END - HOUR,
    END - 2 * HOUR,
    END - 3 * HOUR,
  ]
  candle = pages[0][0]
  assert (candle.volume, candle.quote_volume, candle.trades) == (3, 4, 5)
  assert requests == [
    {
      'interval': 'CI_1_H',
      'type': 'TRADE',
      'start_time': END - 3 * HOUR,
      'end_time': END,
      'limit': 1000,
    }
  ]
  assert [p async for p in history.candles(shared, BTC, '1h', END, END)] == []


async def test_candle_pages_retry_without_duplicates(shared: Shared, fake: Any):
  """A failed later page is fetched again under an SDK retry; rows appear once."""
  calls: list[int] = []
  pages: list[list[dict[str, Any]]] = [
    [
      {
        'open_time': END - (2 * page + i + 1) * HOUR,
        'open': Decimal(1),
        'high': Decimal(1),
        'low': Decimal(1),
        'close': Decimal(1),
        'volume_b': Decimal(1),
        'volume_q': Decimal(1),
        'trades': 1,
      }
      for i in range(2)
    ]
    for page in range(3)
  ]
  fake.market.candlesticks_paged = lambda *a, **k: pager(pages, calls, fail_at=1)  # pyright: ignore[reportUnknownLambdaType]
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    rows = [
      c
      async for p in history.candles(shared, BTC, '1h', END - 10 * HOUR, END)
      for c in p
    ]
  assert calls == [0, 1, 1, 2]
  assert [c.time for c in rows] == [END - i * HOUR for i in range(1, 7)]


async def test_fill_bounds_are_inclusive_at_microseconds(shared: Shared, fake: Any):
  """The venue compares nanoseconds: the end goes out a microsecond later, and both
  bounds are applied locally."""
  requests: list[dict[str, Any]] = []
  start = END - HOUR
  rows = [
    fill(END + MICRO),
    fill(END),
    fill(start + 30 * timedelta(minutes=1), is_buyer=False, is_taker=False),
    fill(start),
    fill(start - MICRO),
  ]
  fake.trading.fill_history_paged = recorder([rows], requests, [])
  trades = [
    t
    async for p in history.trades_history(shared, BTC, start, END, kind='PERPETUAL')
    for t in p
  ]
  assert [t.time for t in trades] == [END, start + 30 * timedelta(minutes=1), start]
  assert requests == [
    {
      'kind': ['PERPETUAL'],
      'base': ['BTC'],
      'quote': ['USDT'],
      'start_time': start,
      'end_time': END + MICRO,
      'limit': 1000,
    }
  ]
  sell = trades[1]
  assert (sell.qty, sell.maker) == (Decimal('-0.002'), True)
  bought = trades[0]
  assert bought.order_id == bought.client_order_id == '9759235347865617030'
  assert bought.fee is not None and (bought.fee.amount, bought.fee.asset) == (
    Decimal('0.073651'),
    'USDT',
  )
  assert not isinstance(bought, ExchangeTrade)


async def test_exchange_fills_carry_their_market(shared: Shared, fake: Any):
  """Exchange-wide fills filter by kind only and name their instrument."""
  requests: list[dict[str, Any]] = []
  rows = [fill(END), fill(END - HOUR, instrument='ETH_USDT_Perp')]
  fake.trading.fill_history_paged = recorder([rows], requests, [])
  trades = [
    t
    async for p in history.trades_history(
      shared, None, END - HOUR, END, kind='PERPETUAL'
    )
    for t in p
  ]
  assert [getattr(t, 'market_id') for t in trades] == [BTC, 'ETH_USDT_Perp']
  assert all(isinstance(t, ExchangeTrade) for t in trades)
  assert 'base' not in requests[0] and requests[0]['kind'] == ['PERPETUAL']


async def test_fill_pages_retry_without_duplicates(shared: Shared, fake: Any):
  """A later fills page failing once is fetched again; every fill appears once."""
  calls: list[int] = []
  pages = [[fill(END - i * HOUR)] for i in range(3)]
  fake.trading.fill_history_paged = lambda **k: pager(pages, calls, fail_at=1)  # pyright: ignore[reportUnknownLambdaType]
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    trades = [
      t
      async for p in history.trades_history(
        shared, BTC, END - 5 * HOUR, END, kind='PERPETUAL'
      )
      for t in p
    ]
  assert calls == [0, 1, 1, 2]
  assert [t.time for t in trades] == [END, END - HOUR, END - 2 * HOUR]


def rate(time: datetime, value: str, hours: int) -> dict[str, Any]:
  """A `funding_rate` row, the rate in percentage points."""
  return {
    'instrument': BTC,
    'funding_rate': Decimal(value),
    'funding_time': time,
    'mark_price': Decimal(81900),
    'funding_rate_8_h_avg': Decimal(value),
    'funding_interval_hours': hours,
  }


async def test_funding_rates_drop_minute_rows(shared: Shared, fake: Any):
  """Percentage points become fractions; `funding_interval_hours == 0` rows (one per
  minute before 2025-10-15) are not settlements; both bounds are inclusive."""
  requests: list[dict[str, Any]] = []
  cutover = datetime(2025, 10, 15, 16, tzinfo=timezone.utc)
  rows = [
    rate(cutover + 8 * HOUR, '0.0057', 8),
    rate(cutover, '0.01', 8),
    rate(cutover - 8 * HOUR, '-0.0096', 0),
    rate(cutover - 8 * HOUR - timedelta(minutes=1), '-0.0039', 0),
  ]
  fake.market.funding_rate_paged = recorder([rows], requests, [])
  rates = [
    r
    async for p in history.funding_rates(shared, BTC, cutover - 9 * HOUR, cutover)
    for r in p
  ]
  assert [(r.time, r.rate) for r in rates] == [(cutover, Decimal('0.0001'))]
  assert requests[0]['start_time'] == cutover - 9 * HOUR
  assert requests[0]['end_time'] == cutover + MICRO
  open_ended = [
    r async for p in history.funding_rates(shared, BTC, None, None) for r in p
  ]
  assert [r.rate for r in open_ended] == [Decimal('0.000057'), Decimal('0.0001')]
  assert (requests[1]['start_time'], requests[1]['end_time']) == (None, None)


def payment(time: datetime, amount: str, instrument: str = BTC) -> dict[str, Any]:
  """A `funding_payment_history` row: `amount` is positive when paid."""
  return {
    'event_time': time,
    'sub_account_id': '1',
    'instrument': instrument,
    'currency': 'USDT',
    'amount': Decimal(amount),
    'tx_id': '1',
  }


async def test_funding_payments_are_received_positive(shared: Shared, fake: Any):
  """The venue's paid-positive `amount` is negated (ADR 0035), within inclusive bounds."""
  requests: list[dict[str, Any]] = []
  rows = [
    payment(END + MICRO, '9'),
    payment(END, '0.05'),
    payment(END - 8 * HOUR, '-0.013'),
    payment(END - 9 * HOUR, '1'),
  ]
  fake.trading.funding_payment_history_paged = recorder([rows], requests, [])
  paid = [
    p
    async for page in history.funding_payments(shared, BTC, END - 8 * HOUR, END)
    for p in page
  ]
  assert [(p.time, p.amount) for p in paid] == [
    (END, Decimal('-0.05')),
    (END - 8 * HOUR, Decimal('0.013')),
  ]
  assert requests[0] == {
    'instrument': BTC,
    'start_time': END - 8 * HOUR,
    'end_time': END + MICRO,
    'limit': 1000,
  }


async def test_exchange_funding_payments_carry_their_market(shared: Shared, fake: Any):
  """Exchange-wide payments filter by kind and name their instrument."""
  requests: list[dict[str, Any]] = []
  rows = [payment(END, '-0.01', 'ETH_USDT_Perp')]
  fake.trading.funding_payment_history_paged = recorder([rows], requests, [])
  paid = [
    p
    async for page in history.funding_payments(shared, None, END - HOUR, END)
    for p in page
  ]
  assert paid == [
    ExchangeFundingPayment(amount=Decimal('0.01'), time=END, market_id='ETH_USDT_Perp')
  ]
  assert requests[0]['kind'] == ['PERPETUAL'] and 'instrument' not in requests[0]


@pytest.mark.parametrize('read', ['trades_history', 'funding_payments'])
async def test_account_history_needs_an_api_key(
  make_fake: Any, make_shared: Any, read: str
):
  """A public client raises `AuthError` before any request."""
  shared = make_shared(make_fake(api_key=False))
  walk = (
    history.trades_history(shared, BTC, END - HOUR, END, kind='PERPETUAL')
    if read == 'trades_history'
    else history.funding_payments(shared, BTC, END - HOUR, END)
  )
  with pytest.raises(AuthError):
    await anext(aiter(walk))
