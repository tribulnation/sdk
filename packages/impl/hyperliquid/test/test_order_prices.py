"""Price grid checks and serialization regressions for Hyperliquid orders."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from typed_hyperliquid.core.wire import dump_request
from typed_hyperliquid.exchange.order import Request
from typing_extensions import cast

from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin
from tribulnation.hyperliquid.market.impl.orders import _export_order


def market() -> PerpMarketMixin:
  """A perpetual with `szDecimals` 0: prices take up to 6 decimals."""
  return cast(
    PerpMarketMixin, SimpleNamespace(asset_id=0, tick_size=Decimal('0.000001'))
  )


@pytest.mark.parametrize(
  'price', ['0.130205', '1234.56', '9999.99', '0.0000001', '10000.5']
)
def test_off_grid_price_raises(price: str):
  """More than 5 significant figures (integers aside) or decimals than the tick: the
  order is refused before signing rather than rounded."""
  with pytest.raises(ValueError, match='off the Hyperliquid grid'):
    _export_order(
      market(), {'type': 'LIMIT', 'price': Decimal(price), 'qty': Decimal('1')}, {}
    )


@pytest.mark.parametrize('price', ['0.1302', '10', '10000', '123456', '0.000123'])
def test_exported_order_price_serialization(price: str):
  """The typed client's pre-signing payload must contain an unpadded price."""
  order = _export_order(
    market(),
    {'type': 'LIMIT', 'price': Decimal(price), 'qty': Decimal('100')},
    {},
  )
  request = Request(orders=[order], grouping='na')
  wire = dump_request(request, Request)
  assert wire['orders'][0]['p'] == price


@pytest.mark.parametrize(
  ('qty', 'expected'),
  [
    ('4E+1', '40'),
    ('-4E+1', '40'),
    ('1E+2', '100'),
    ('35', '35'),
    ('0.5', '0.5'),
    ('2.50', '2.5'),
  ],
)
def test_exported_order_size_serialization(qty: str, expected: str):
  """Sizes rounded by the SDK rules arrive normalized (`40` is `4E+1`); the venue only parses positional decimals."""
  order = _export_order(
    market(),
    {'type': 'LIMIT', 'price': Decimal('4.9557'), 'qty': Decimal(qty)},
    {},
  )
  request = Request(orders=[order], grouping='na')
  wire = dump_request(request, Request)
  assert wire['orders'][0]['s'] == expected


def test_exported_order_price_serialization_from_normalized_integer():
  """A tick-rounded price above 10000 arrives as `1.2E+5` and must still be sent positionally."""
  order = _export_order(
    market(),
    {'type': 'LIMIT', 'price': Decimal('1.2E+5'), 'qty': Decimal('0.01')},
    {},
  )
  request = Request(orders=[order], grouping='na')
  wire = dump_request(request, Request)
  assert wire['orders'][0]['p'] == '120000'
