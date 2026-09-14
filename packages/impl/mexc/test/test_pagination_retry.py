"""MEXC report pages and time windows retry without restarting history."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing_extensions import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError
from typed_mexc import MEXC

from tribulnation.mexc.reporting import history
from tribulnation.mexc.reporting.main import Report
from tribulnation.sdk import Context, NetworkError

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def test_funding_page_retry():
  """Funding pagination resumes the failing page, including empty result pages."""
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[Any], int | None]:
    """Fail page two once."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    return [], state + 1 if state < 2 else None

  account = SimpleNamespace(
    funding_records_paged=Mock(return_value=PaginatedResponse(0, fetch))
  )
  client = cast(
    MEXC,
    SimpleNamespace(futures=SimpleNamespace(http=SimpleNamespace(account=account))),
  )
  report = Report(client=client, streams={})
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    assert [row async for row in history.funding(report, START, START)] == []
  assert calls == [0, 1, 1, 2]


@pytest.mark.parametrize(
  'method,endpoint',
  [
    ('deposits', 'deposit_history'),
    ('withdrawals', 'withdraw_history'),
  ],
)
async def test_capital_window_retry(method: str, endpoint: str):
  """A failed second time window leaves the first window completed."""
  request = AsyncMock(side_effect=[[], ClientNetworkError('disconnected'), []])
  wallet = SimpleNamespace(**{endpoint: request})
  client = cast(
    MEXC, SimpleNamespace(spot=SimpleNamespace(http=SimpleNamespace(wallet=wallet)))
  )
  report = Report(client=client, streams={})
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    assert [
      row
      async for row in getattr(history, method)(
        report, START, START + timedelta(days=8)
      )
    ] == []
  windows = [call.kwargs['start_time'] for call in request.await_args_list]
  assert windows == [
    START,
    START + timedelta(days=7, milliseconds=1),
    START + timedelta(days=7, milliseconds=1),
  ]
