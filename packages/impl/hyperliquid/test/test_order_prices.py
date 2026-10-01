"""Price rounding and serialization regressions for Hyperliquid orders."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from typed_hyperliquid.core.wire import dump_request
from typed_hyperliquid.exchange.order import Request
from typing_extensions import cast

from tribulnation.hyperliquid.core import round_price
from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin
from tribulnation.hyperliquid.market.impl.orders import _export_order


@pytest.mark.parametrize(
  ('price', 'expected'),
  [
    ('0.1302', '0.1302'),
    ('0.130200', '0.1302'),
    ('0.130205', '0.13021'),
    ('0.130199', '0.1302'),
    ('0.0001234', '0.0001234'),
    ('1234.56', '1234.6'),
    ('1', '1'),
    ('10.00', '10'),
    ('100', '100'),
    ('9999.99', '10000'),
    ('123456', '123456'),
    ('1.2E+5', '120000'),
    ('0.0000', '0'),
  ],
)
def test_round_price_representation(price: str, expected: str):
  """Keep venue precision and remove fractional padding, including after a carry."""
  assert str(round_price(Decimal(price))) == expected


@pytest.mark.parametrize('price', ['0.1302', '10', '10000'])
def test_exported_order_price_serialization(price: str):
  """The typed client's pre-signing payload must contain an unpadded price."""
  market = cast(PerpMarketMixin, SimpleNamespace(asset_id=0))
  order = _export_order(
    market,
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
  market = cast(PerpMarketMixin, SimpleNamespace(asset_id=0))
  order = _export_order(
    market,
    {'type': 'LIMIT', 'price': Decimal('4.9557'), 'qty': Decimal(qty)},
    {},
  )
  request = Request(orders=[order], grouping='na')
  wire = dump_request(request, Request)
  assert wire['orders'][0]['s'] == expected


def test_exported_order_price_serialization_from_normalized_integer():
  """A tick-rounded price above 10000 arrives as `1.2E+5` and must still be sent positionally."""
  market = cast(PerpMarketMixin, SimpleNamespace(asset_id=0))
  order = _export_order(
    market,
    {'type': 'LIMIT', 'price': Decimal('1.2E+5'), 'qty': Decimal('0.01')},
    {},
  )
  request = Request(orders=[order], grouping='na')
  wire = dump_request(request, Request)
  assert wire['orders'][0]['p'] == '120000'
