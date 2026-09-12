"""Portfolio history works without dates or caller-supplied traded symbols."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_binance import Binance
from typed_binance.spot.http.account.my_trades import MyTrades
from typed_binance.spot.http.market.exchange_info import (
  ExchangeInfoEndpoint as SpotInfo,
)
from typing_extensions import AsyncIterator

from tribulnation.binance.reporting import Reporting
from tribulnation.binance.reporting.history import History
from tribulnation.binance.reporting.util import months_before
from tribulnation.sdk.reporting import HistoryRecord, SpotTrade

END = datetime(2026, 9, 9, tzinfo=timezone.utc)
START = END - timedelta(days=1)


@pytest.fixture
def report():
  """Build the real adapter; each test replaces the endpoint methods it reaches."""
  return Reporting(client=Binance.new(public=True))


@pytest.mark.parametrize(
  'start,end', [(None, END), (START, None), (None, None), (START, END)]
)
async def test_optional_bounds_are_resolved_per_source(
  report: Reporting,
  monkeypatch: pytest.MonkeyPatch,
  start: datetime | None,
  end: datetime | None,
):
  """Every omitted-bound combination calls only the four supported spot-side sources."""
  calls: dict[str, tuple[datetime | None, datetime]] = {}

  def install(name: str):
    """Capture the source window without network access."""

    async def source(
      self: History,
      lower: datetime | None,
      upper: datetime,
      *,
      id: str,
    ) -> AsyncIterator[HistoryRecord]:
      """Record the resolved bounds of this source."""
      calls[name] = lower, upper
      for record in ():
        yield record

    monkeypatch.setattr(History, name, source)

  for name in (
    'crypto_deposits',
    'crypto_withdrawals',
    'internal_transfers',
    'spot_trades',
  ):
    install(name)
  before = datetime.now(timezone.utc)
  assert [record async for record in report.history(start, end)] == []
  after = datetime.now(timezone.utc)
  assert len(calls) == 4
  upper = calls['spot_trades'][1]
  assert upper == end if end is not None else before <= upper <= after
  assert {bounds[1] for bounds in calls.values()} == {upper}
  assert calls['crypto_deposits'][0] == (start or upper - timedelta(days=90))
  assert calls['crypto_withdrawals'][0] == calls['crypto_deposits'][0]
  assert calls['internal_transfers'][0] == (start or months_before(upper, 6))
  assert calls['spot_trades'][0] == start


async def test_spot_discovers_all_symbols_and_pages_by_id(
  report: Reporting,
  monkeypatch: pytest.MonkeyPatch,
):
  """No holdings filter, caller market list or time/fromId combination is needed."""
  monkeypatch.setattr(
    SpotInfo,
    'exchange_info',
    AsyncMock(
      return_value={
        'symbols': [{'symbol': 'BTCUSDT'}, {'symbol': 'ETHUSDT'}],
      }
    ),
  )
  row: dict[str, object] = {
    'id': 0,
    'time': START,
    'symbol': 'BTCUSDT',
    'qty': Decimal(1),
    'isBuyer': True,
    'price': Decimal(2),
    'orderId': 1,
    'commission': Decimal(0),
    'commissionAsset': 'USDT',
  }
  first: list[dict[str, object]] = [{**row, 'id': index} for index in range(1000)]
  request = AsyncMock(
    side_effect=[first, [{**row, 'id': 1000, 'time': END + timedelta(seconds=1)}], []]
  )
  monkeypatch.setattr(MyTrades, 'my_trades', request)
  records = [record async for record in report.spot_trades(START, END, id='fixture')]
  assert len(records) == 1000
  assert all(isinstance(record.observations[0], SpotTrade) for record in records)
  assert [call.kwargs['symbol'] for call in request.await_args_list] == [
    'BTCUSDT',
    'BTCUSDT',
    'ETHUSDT',
  ]
  assert [call.kwargs['from_id'] for call in request.await_args_list] == [0, 1000, 0]
  assert all(
    'start_time' not in call.kwargs and 'end_time' not in call.kwargs
    for call in request.await_args_list
  )


def test_calendar_retention_clamps_month_end():
  """Six calendar months is not a fixed 180-day duration."""
  assert months_before(datetime(2026, 8, 31, tzinfo=timezone.utc), 6) == datetime(
    2026, 2, 28, tzinfo=timezone.utc
  )


@pytest.mark.parametrize('start,end', [(END, START), (START.replace(tzinfo=None), END)])
async def test_invalid_explicit_bounds_fail_before_network(
  report: Reporting,
  start: datetime,
  end: datetime,
):
  """Optional bounds do not permit reversed or timezone-naive ranges."""
  with pytest.raises(ValueError):
    _ = [record async for record in report.history(start, end)]
