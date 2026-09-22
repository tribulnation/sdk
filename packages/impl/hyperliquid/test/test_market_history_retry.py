"""Market history retries typed-client page failures at the request boundary."""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing_extensions import Any, cast
from unittest.mock import Mock

import pytest
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError
from typed_hyperliquid import Hyperliquid

from tribulnation.hyperliquid.market.impl import funding, trades
from tribulnation.hyperliquid.market.impl.mixin import (
  PerpMarketMixin,
  Shared,
  SharedMixin,
)
from tribulnation.sdk import Context, NetworkError
from tribulnation.sdk.market import FundingPayment

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
  'method,endpoint',
  [
    ('funding_rates', 'funding_history_paged'),
    ('funding_payments', 'user_funding_paged'),
    ('trades_history', 'user_fills_by_time_paged'),
  ],
)
async def test_market_page_retry(
  monkeypatch: pytest.MonkeyPatch, method: str, endpoint: str
):
  """Each history source emits successful pages once after a transient disconnect."""
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[dict[str, Any]], int | None]:
    """Serve native funding/fill fields and fail page two once."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    row: dict[str, Any] = {
      'time': START,
      'fundingRate': '0.01',
      'delta': {'coin': 'BTC', 'usdc': '1'},
      'coin': 'BTC',
      'side': 'B',
      'px': '1',
      'sz': '1',
      'fee': '0',
      'feeToken': 'USDC',
      'tid': state,
    }
    return [row], state + 1 if state < 2 else None

  async def resolve_asset_index(asset: str) -> int:
    """Resolve the fixture's fee asset without a metadata request."""
    return 0

  async with Hyperliquid.new(public=True) as client:
    monkeypatch.setattr(
      type(client.info), endpoint, Mock(return_value=PaginatedResponse(0, fetch))
    )
    owner = SharedMixin(shared=Shared(client=client, maybe_address=None))
    market = cast(
      PerpMarketMixin,
      SimpleNamespace(
        client=client,
        asset_name='BTC',
        address='0xfixture',
        call_hyperliquid=owner.call_hyperliquid,
        shared=SimpleNamespace(resolve_asset_index=resolve_asset_index),
      ),
    )
    fn = (
      trades.trades_history if method == 'trades_history' else getattr(funding, method)
    )
    with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
      pages = [page async for page in fn(market, START, START)]
  assert [len(page) for page in pages] == [1, 1, 1]
  assert calls == [0, 1, 1, 2]
  if method == 'trades_history':
    assert [trade.id for page in pages for trade in page] == ['0', '1', '2']

  if method == 'funding_payments':
    for page in pages:
      for payment in page:
        assert isinstance(payment, FundingPayment)
        assert payment.amount == -1
