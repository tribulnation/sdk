"""Public INTX history preserves SDK identity, inclusive bounds and page ownership."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from typed_core import PaginatedResponse
from typed_coinbase import Coinbase
from typed_coinbase.international.instruments.funding import Funding, InstrumentFunding
from typed_coinbase.international.instruments.get import Get
from tribulnation.coinbase.core.mixin import Shared
from tribulnation.coinbase.market.perp_market import PerpMarket
from tribulnation.sdk.core import ApiError

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def row(hour: int, instrument_id: str = '123') -> InstrumentFunding:
  """Build a validated settlement with exact signed relative funding."""
  return {
    'instrument_id': instrument_id,
    'funding_rate': Decimal('-0.000001'),
    'mark_price': Decimal('10'),
    'event_time': START + timedelta(hours=hour),
  }


def instrument_request(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
  """Resolve the canonical Advanced Trade ID to a different numeric INTX ID."""
  request = AsyncMock(
    return_value={'symbol': 'BTC-PERP', 'type': 'PERP', 'instrument_id': '123'}
  )
  monkeypatch.setattr(Get, 'get', request)
  return request


async def test_bounds_duplicates_and_numeric_identity(monkeypatch: pytest.MonkeyPatch):
  """Page overlap never duplicates events; both inclusive endpoints survive."""
  identity = instrument_request(monkeypatch)
  fetch = AsyncMock(
    side_effect=[([row(4), row(3), row(2)], 1), ([row(2), row(1), row(0)], None)]
  )
  paged = Mock()

  def paging(
    self: Funding, instrument: str, *, result_limit: int
  ) -> PaginatedResponse[InstrumentFunding, int]:
    """Record pager arguments while retaining the real retryable page primitive."""
    paged(instrument, result_limit=result_limit)
    return PaginatedResponse(0, fetch)

  monkeypatch.setattr(Funding, 'funding_paged', paging)
  client = Coinbase.new(public=True)
  async with client:
    market = PerpMarket(shared=Shared(client=client), product_id='BTC-PERP-INTX')
    result = await market.funding_rates(
      START + timedelta(hours=1), START + timedelta(hours=3)
    )
  assert [item.time for item in result] == [
    row(3)['event_time'],
    row(2)['event_time'],
    row(1)['event_time'],
  ]
  assert all(item.rate == Decimal('-0.000001') for item in result)
  identity.assert_awaited_once_with('BTC-PERP')
  paged.assert_called_once_with('123', result_limit=100)
  assert fetch.await_count == 2


async def test_no_bounds_walks_to_earliest_available(monkeypatch: pytest.MonkeyPatch):
  """Omitted bounds do not silently limit history to one recent page."""
  instrument_request(monkeypatch)
  fetch = AsyncMock(side_effect=[([row(2)], 1), ([row(1)], None)])

  def paging(
    self: Funding, instrument: str, *, result_limit: int
  ) -> PaginatedResponse[InstrumentFunding, int]:
    """Return two explicitly bounded fake pages."""
    return PaginatedResponse(0, fetch)

  monkeypatch.setattr(Funding, 'funding_paged', paging)
  async with Coinbase.new(public=True) as client:
    market = PerpMarket(shared=Shared(client=client), product_id='BTC-PERP-INTX')
    assert len(await market.funding_rates()) == 2


async def test_wrong_instrument_row_is_rejected(monkeypatch: pytest.MonkeyPatch):
  """Funding belonging to a different instrument cannot be silently rekeyed."""
  instrument_request(monkeypatch)
  monkeypatch.setattr(
    Funding, 'funding', AsyncMock(return_value={'results': [row(1, 'WRONG')]})
  )
  async with Coinbase.new(public=True) as client:
    market = PerpMarket(shared=Shared(client=client), product_id='BTC-PERP-INTX')
    with pytest.raises(ApiError, match='different instrument'):
      await market.funding_rates()


@pytest.mark.parametrize('product', ['BTC-USD', 'BTC-PERP'])
async def test_non_sdk_perpetual_id_rejected(
  monkeypatch: pytest.MonkeyPatch, product: str
):
  """The adapter cannot quietly accept a spot or native-INTX ID as an SDK product."""
  request = instrument_request(monkeypatch)
  async with Coinbase.new(public=True) as client:
    market = PerpMarket(shared=Shared(client=client), product_id=product)
    with pytest.raises(ValueError, match='INTX perpetual ID'):
      await market.funding_rates()
  request.assert_not_awaited()


@pytest.mark.parametrize(
  'start,end',
  [(START + timedelta(hours=1), START), (START.replace(tzinfo=None), START)],
)
async def test_invalid_bounds_fail_before_network(
  monkeypatch: pytest.MonkeyPatch, start: datetime, end: datetime
):
  """Reversed or timezone-naive windows are rejected locally."""
  request = instrument_request(monkeypatch)
  async with Coinbase.new(public=True) as client:
    market = PerpMarket(shared=Shared(client=client), product_id='BTC-PERP-INTX')
    with pytest.raises(ValueError):
      await market.funding_rates(start, end)
  request.assert_not_awaited()
