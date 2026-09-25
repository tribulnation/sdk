"""Real SDK page boundaries preserve completed work across transient failures."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Any
import pytest
from typed_core import NetworkError as ClientNetworkError, PaginatedResponse
from typed_aster.futures.market.klines import Klines
from typed_aster.futures.market.funding_rate import FundingRateEndpoint
from typed_aster.futures.account.income import IncomeEndpoint
from typed_aster.spot.account.transaction_history import TransactionHistory
from tribulnation.aster import AsterMarket, Report
from tribulnation.aster.market.market import PerpMarket
from tribulnation.sdk import Context, NetworkError

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize('collect', [False, True])
async def test_candles_retry_only_failed_window(
  collect: bool, monkeypatch: pytest.MonkeyPatch
):
  """An empty first page does not truncate history; retrying page two repeats no rows."""
  timestamp = START + timedelta(minutes=500)
  row: list[datetime | Decimal | int | str] = [
    timestamp,
    Decimal(1),
    Decimal(2),
    Decimal(1),
    Decimal(2),
    Decimal(3),
    timestamp,
    Decimal(4),
    5,
    Decimal(1),
    Decimal(1),
    '0',
  ]
  endpoint = AsyncMock(side_effect=[[], ClientNetworkError('offline'), [row]])
  monkeypatch.setattr(Klines, 'klines', endpoint)
  market = PerpMarket(exchange=AsterMarket.new(public=True).perp, symbol='BTCUSDT')
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    request = market.candles('1m', START, START + timedelta(minutes=501))
    result = await request if collect else [r async for page in request for r in page]
  assert [r.time for r in result] == [timestamp]
  assert [c.kwargs['start_time'] for c in endpoint.await_args_list] == [
    START,
    timestamp,
    timestamp,
  ]
  assert await market.candles('1m', START, START) == []
  with pytest.raises(ValueError, match='timezone-aware'):
    market.candles('1m', START.replace(tzinfo=None), START)


async def test_native_funding_pager_retry(monkeypatch: pytest.MonkeyPatch):
  """A typed pager's continuation is retried inside the SDK request boundary."""
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[Any], int | None]:
    """Fail the second native page once, then return one observed settlement."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('offline')
    return (
      [{'fundingRate': Decimal('.001'), 'fundingTime': START}] if state == 2 else []
    ), state + 1 if state < 2 else None

  def pages(*args: Any, **kwargs: Any):
    """Supply the actual typed-core pagination object."""
    return PaginatedResponse(0, fetch)

  monkeypatch.setattr(FundingRateEndpoint, 'funding_rate_paged', pages)
  exchange = AsterMarket.new(public=True).perp
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    rows = await exchange.funding_rates('BTCUSDT', START, START)
  assert calls == [0, 1, 1, 2]
  assert len(rows) == 1 and rows[0].rate == Decimal('.001')


async def test_report_retry_and_distinct_cash_legs(monkeypatch: pytest.MonkeyPatch):
  """A transaction's base/quote legs survive independently, without restarting pages."""
  calls: list[int] = []

  async def income(state: int) -> tuple[list[Any], int | None]:
    """Emit one native cash record per page and interrupt the second page once."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('offline')
    return [
      {
        'tranId': state,
        'incomeType': 'COMMISSION',
        'asset': 'USDT',
        'income': Decimal('-1'),
        'time': START,
      }
    ], 1 if state == 0 else None

  async def transactions(state: int) -> tuple[list[Any], None]:
    """Two native rows legitimately share a transaction ID."""
    return [
      dict(tranId=1, type=kind, asset=asset, balanceDelta=Decimal(1), time=START)
      for kind, asset in [('TRADE_SOURCE', 'USDT'), ('TRADE_TARGET', 'ASTER')]
    ], None

  def income_pages(*args: Any, **kwargs: Any):
    """Supply the native pager while retaining its retryable fetch state."""
    return PaginatedResponse(0, income)

  def transaction_pages(*args: Any, **kwargs: Any):
    """Supply independent cash legs from the spot pager."""
    return PaginatedResponse(0, transactions)

  monkeypatch.setattr(IncomeEndpoint, 'income_paged', income_pages)
  monkeypatch.setattr(
    TransactionHistory,
    'transaction_history_paged',
    transaction_pages,
  )
  report = Report.new(public=True, mainnet=False)
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    rows = [r async for r in report.history(START, START)]
  assert calls == [0, 1, 1]
  assert len(rows) == 4 and len({r.provenance['id'] for r in rows}) == 4
  assert all(
    r.provenance['service'] == 'aster_testnet'
    for r in rows
    if r.provenance['source'] == 'api'
  )
