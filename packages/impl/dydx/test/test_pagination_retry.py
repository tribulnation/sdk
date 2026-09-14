"""Snapshot and provider pagination retains successful pages across network failures."""

from types import SimpleNamespace
from email.message import Message
from typing_extensions import Any, cast
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
import requests
from google.cloud import bigquery
from google.cloud.bigquery.table import RowIterator
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError
from typed_dydx import Dydx

from tribulnation.dydx.report.snapshots import Snapshots
from tribulnation.dydx.report.history import governance, gcloud
from tribulnation.sdk import ApiError, Context, NetworkError, RateLimited


@pytest.mark.parametrize(
  'method,endpoint',
  [
    ('bank_module_balances', 'bank.all_balances_paged'),
    ('active_delegations', 'staking.delegator_delegations_paged'),
    ('unbonding_delegations', 'staking.delegator_unbonding_delegations_paged'),
  ],
)
async def test_snapshot_page_retry(
  monkeypatch: pytest.MonkeyPatch, method: str, endpoint: str
):
  """A failed chain page is retried without restarting snapshot accumulation."""
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[Any], int | None]:
    """Fail the second page once."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    return [], state + 1 if state < 2 else None

  async with Dydx.mainnet(public=True) as client:
    module, name = endpoint.split('.')
    owner: object = getattr(client.chain, module)
    monkeypatch.setattr(
      type(owner), name, Mock(return_value=PaginatedResponse(0, fetch))
    )
    snapshot = Snapshots.of('dydx1fixture', client)
    with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
      assert await getattr(snapshot, method)() == {}
  assert calls == [0, 1, 1, 2]


async def test_governance_page_retry(monkeypatch: pytest.MonkeyPatch):
  """A raw URL transport failure retries the same governance continuation."""
  first = Mock()
  first.__enter__ = Mock(return_value=first)
  first.__exit__ = Mock(return_value=False)
  first.read.return_value = (
    b'{"proposals": [{"id": "1"}], "pagination": {"next_key": "next"}}'
  )
  last = Mock()
  last.__enter__ = Mock(return_value=last)
  last.__exit__ = Mock(return_value=False)
  last.read.return_value = b'{"proposals": [{"id": "2"}]}'
  request = Mock(side_effect=[first, URLError('disconnected'), last])
  monkeypatch.setattr(governance, 'urlopen', request)
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    rows = await governance.GovernanceHistory('dydx1fixture').governance_proposals()
  assert rows == [{'id': '1'}, {'id': '2'}]
  urls = [call.args[0] for call in request.call_args_list]
  assert urls[0] != urls[1] == urls[2]


@pytest.mark.parametrize('status,error_type', [(429, RateLimited), (403, ApiError)])
async def test_governance_http_errors(
  monkeypatch: pytest.MonkeyPatch,
  status: int,
  error_type: type[Exception],
):
  """HTTP rejection remains distinct from a transport failure."""
  request = Mock(
    side_effect=HTTPError('https://example.test', status, 'rejected', Message(), None)
  )
  monkeypatch.setattr(governance, 'urlopen', request)
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    with pytest.raises(error_type):
      await governance.GovernanceHistory('dydx1fixture').governance_proposals()
  assert request.call_count == 1


async def test_bigquery_result_page_retry():
  """Retry the actual RowIterator request, without closing it or rerunning the job."""
  request = Mock(
    side_effect=[
      {'rows': [{'f': [{'v': '1'}]}], 'pageToken': 'next', 'totalRows': '2'},
      requests.ConnectionError('disconnected'),
      {'rows': [{'f': [{'v': '2'}]}], 'totalRows': '2'},
    ]
  )
  iterator = RowIterator(
    client=Mock(),
    api_request=request,
    path='/results',
    schema=[bigquery.SchemaField('value', 'INTEGER')],
  )
  result = Mock(return_value=iterator)
  job = cast(bigquery.QueryJob, SimpleNamespace(result=result))
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    assert await gcloud.rows(job) == [{'value': 1}, {'value': 2}]
  assert result.call_count == 1
  assert [
    call.kwargs['query_params'].get('pageToken') for call in request.call_args_list
  ] == [None, 'next', 'next']


async def test_market_fills_retry(monkeypatch: pytest.MonkeyPatch):
  """Market fills retain completed pages and emit each trade once."""
  from datetime import datetime, timezone
  from unittest.mock import AsyncMock
  from tribulnation.dydx.market.impl.mixin import ExchangeMixin, MarketMixin
  from tribulnation.dydx.market.impl.trades import trades_history

  start = datetime(2026, 1, 1, tzinfo=timezone.utc)
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[dict[str, Any]], int | None]:
    """Return a native fill per page, failing once on page two."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    return [
      {
        'id': str(state),
        'market': 'BTC-USD',
        'side': 'BUY',
        'price': '1',
        'size': '1',
        'createdAt': start,
        'liquidity': 'MAKER',
        'fee': '0',
      }
    ], state + 1 if state < 2 else None

  async with ExchangeMixin.new() as owner:
    data = owner.indexer.data
    monkeypatch.setattr(
      type(data), 'get_fills_paged', Mock(return_value=PaginatedResponse(0, fetch))
    )
    monkeypatch.setattr(
      type(data),
      'get_subaccounts',
      AsyncMock(return_value={'subaccounts': [{'subaccountNumber': 0}]}),
    )
    market = cast(
      MarketMixin,
      SimpleNamespace(
        address='dydx1fixture',
        market='BTC-USD',
        indexer=owner.indexer,
        call_dydx=owner.call_dydx,
      ),
    )
    with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
      rows = await trades_history(market, start, start)
  assert [row.id for row in rows] == ['0', '1', '2']
  assert calls == [0, 1, 1, 2]
