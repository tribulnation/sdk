"""Classic reporting retries failed pages without replaying successful cursors."""

from datetime import datetime, timezone
from typing_extensions import Any
from unittest.mock import Mock

import pytest
from typed_bitget import Bitget
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError

from tribulnation.bitget.reporting.history.futures import FuturesHistory
from tribulnation.bitget.reporting.history.margin import MarginHistory
from tribulnation.bitget.reporting.history.spot import SpotHistory
from tribulnation.bitget.reporting.history.util import id_pages
from tribulnation.sdk import Context, NetworkError


@pytest.mark.parametrize(
  'kind,method,endpoint,margin_type',
  [
    ('spot', 'flows', 'classic.tax.spot_records_paged', None),
    ('futures', 'flows', 'classic.tax.futures_records_paged', None),
    ('futures', 'trades', 'classic.mix.order.fill_history_paged', None),
    ('margin', 'flow_records', 'classic.tax.margin_records_paged', 'crossed'),
    ('margin', 'flow_records', 'classic.tax.margin_records_paged', 'isolated'),
    ('margin', 'symbol_trades', 'classic.margin.cross.order.fills_paged', 'crossed'),
    (
      'margin',
      'symbol_trades',
      'classic.margin.isolated.order.fills_paged',
      'isolated',
    ),
  ],
)
async def test_report_page_retry(
  monkeypatch: pytest.MonkeyPatch,
  kind: str,
  method: str,
  endpoint: str,
  margin_type: str | None,
):
  """Every paged report source resumes at the failed page, including empty pages."""
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[Any], int | None]:
    """Fail page two once and retain the original cursor."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    return [], state + 1 if state < 2 else None

  async with Bitget.new(public=True) as client:
    owner: object = client
    *parts, name = endpoint.split('.')
    for part in parts:
      owner = getattr(owner, part)
    monkeypatch.setattr(
      type(owner), name, Mock(return_value=PaginatedResponse(0, fetch))
    )
    histories: dict[str, SpotHistory | MarginHistory | FuturesHistory] = {
      'spot': SpotHistory(client=client, symbols_cache={}),
      'futures': FuturesHistory(client=client),
      'margin': MarginHistory(client=client, symbols_cache={}),
    }
    history = histories[kind]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    args = ([margin_type] if margin_type else []) + (
      ['BTCUSDT'] if method == 'symbol_trades' else []
    )
    with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
      assert [row async for row in getattr(history, method)(*args, start, start)] == []
    assert calls == [0, 1, 1, 2]


async def test_id_cursor_retry_does_not_duplicate_rows():
  """The shared spot fill/deposit/withdrawal pager advances only after success."""
  calls: list[str | None] = []

  async def fetch(cursor: str | None) -> list[str]:
    """Return two rows and fail once between them."""
    calls.append(cursor)
    if calls == [None, 'a']:
      raise ClientNetworkError('disconnected')
    return ['a'] if cursor is None else ['b'] if cursor == 'a' else []

  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    rows = [row async for page in id_pages(fetch, lambda row: row) for row in page]
  assert rows == ['a', 'b']
  assert calls == [None, 'a', 'a', 'b']
