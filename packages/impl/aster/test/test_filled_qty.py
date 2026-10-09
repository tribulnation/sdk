"""`OrderResponse.filled_qty` from Aster's placement answers."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_aster.futures.trade.place_order import PlaceOrder as PerpOrders
from typed_aster.spot.trade.place_order import PlaceOrder as SpotOrders
from tribulnation.aster import AsterMarket
from tribulnation.aster.market.markets import PerpMarket, SpotMarket
from tribulnation.sdk.market import Order

MARKET: Order = {'type': 'MARKET', 'qty': Decimal('-3'), 'price': Decimal('0.75')}


def perp(monkeypatch: pytest.MonkeyPatch, row: dict[str, object]) -> PerpMarket:
  """A testnet perpetual market whose placement answers `row`."""
  monkeypatch.setattr(PerpOrders, 'place_order', AsyncMock(return_value=row))
  shared = AsterMarket.new(public=True, mainnet=False).shared
  return PerpMarket(shared=shared, symbol='ASTERUSDT')


@pytest.mark.parametrize(
  ('status', 'executed'),
  [
    ('FILLED', Decimal('3')),
    ('EXPIRED', Decimal('1.5')),
    ('NEW', Decimal('0')),
    ('PARTIALLY_FILLED', Decimal('0.25')),
  ],
)
async def test_perp_reports_executed_qty(
  status: str, executed: Decimal, monkeypatch: pytest.MonkeyPatch
):
  """The perpetual `RESULT` answer's unsigned `executedQty`, even for a sell."""
  row: dict[str, object] = {'orderId': 9, 'status': status, 'executedQty': executed}

  response = await perp(monkeypatch, row).place_order(MARKET)

  assert response.filled_qty == executed
  assert response.details == row


async def test_perp_without_executed_qty_is_unknown(monkeypatch: pytest.MonkeyPatch):
  """A row that omits `executedQty` reports no execution."""
  response = await perp(monkeypatch, {'orderId': 9}).place_order(MARKET)

  assert response.filled_qty is None


async def test_spot_is_unknown(monkeypatch: pytest.MonkeyPatch):
  """Spot answers before matching, so its `executedQty` 0 is not an execution."""
  row: dict[str, object] = {
    'orderId': 9,
    'status': 'NEW',
    'executedQty': Decimal('0'),
  }
  monkeypatch.setattr(SpotOrders, 'place_order', AsyncMock(return_value=row))
  shared = AsterMarket.new(public=True, mainnet=False).shared

  response = await SpotMarket(shared=shared, symbol='ASTERUSDT').place_order(MARKET)

  assert response.filled_qty is None
  assert response.details == row
