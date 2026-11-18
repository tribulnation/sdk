"""Every venue's offline order builder reads a float `qty` and `price` by their decimal
digits (`to_decimal`), not their binary expansion.

`Decimal(0.1)` is `0.1000000000000000055511151231257827...`: sent as is, it is off any
size grid, and a builder that checks the grid refuses it. Each case builds a `LIMIT`
order from floats that are on its venue's grid but not exactly representable in binary,
and reads back the size and price the payload carries. Lighter and Extended build inside
their async `place_order`; their cases live in each venue's `test_orders.py`, over its
fakes.
"""

from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, Callable, cast

import pytest

from tribulnation.sdk.market import Order

ORDER: Order = {'type': 'LIMIT', 'qty': 0.1, 'price': 2345.6}
"""A buy of `0.1` at `2345.6`: neither float is exactly representable in binary."""
QTY, PRICE = Decimal('0.1'), Decimal('2345.6')


def aster() -> tuple[Any, Any]:
  """Aster's native order: positional decimals."""
  from tribulnation.aster.market.markets import native_order

  o = native_order(ORDER)
  return o.quantity, o.price


def bit2me() -> tuple[Any, Any]:
  """Bit2Me's limit request: decimal strings."""
  from tribulnation.bit2me.market.impl.orders import dump_order

  o = cast(dict[str, Any], dump_order('BTC/EUR', ORDER))
  return Decimal(o['amount']), Decimal(o['price'])


def bybit() -> tuple[Any, Any]:
  """Bybit's limit request: decimal strings."""
  from tribulnation.bybit.market.impl.parse import order_request

  o = cast(dict[str, Any], order_request('linear', 'BTCUSDT', ORDER))
  return Decimal(o['qty']), Decimal(o['price'])


def coinbase() -> tuple[Any, Any]:
  """Coinbase's GTC limit configuration."""
  from tribulnation.coinbase.market.impl.orders import order_configuration

  o = cast(dict[str, Any], order_configuration(ORDER))['limit_limit_gtc']
  return o['base_size'], o['limit_price']


def dydx() -> tuple[Any, Any]:
  """dYdX's order parameters, before the client quantizes them."""
  from tribulnation.dydx.market.impl.orders import export_order

  o = cast(dict[str, Any], export_order(ORDER, {}))
  return o['size'], o['price']


def grvt() -> tuple[Any, Any]:
  """GRVT's one-leg limit order."""
  from tribulnation.grvt.market.orders import new_order

  leg = cast(dict[str, Any], new_order('BTC_USDT_Perp', ORDER, '1'))['legs'][0]
  return leg['size'], leg['limit_price']


def hyperliquid() -> tuple[Any, Any]:
  """Hyperliquid's wire order, on a perpetual with a `0.1` tick (5 size decimals)."""
  from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin
  from tribulnation.hyperliquid.market.impl.orders import _export_order

  market = SimpleNamespace(asset_id=0, tick_size=Decimal('0.1'))
  o = _export_order(cast(PerpMarketMixin, market), ORDER, {})
  return o['s'], o['p']


def margin_trade() -> tuple[Any, Any]:
  """margin.trade's order spec, on a perpetual with a `0.1` tick (5 size decimals)."""
  from tribulnation.margin_trade.market.markets import NativeMarket

  market = SimpleNamespace(asset=0, sz_decimals=5, price_decimals=6)
  o = NativeMarket.order_spec(cast(NativeMarket, market), ORDER, {})
  return o['s'], o['p']


def mexc() -> tuple[Any, Any]:
  """MEXC's spot order request."""
  from tribulnation.mexc.market.impl.orders import _dump_order

  o = cast(dict[str, Any], _dump_order('BTCUSDT', ORDER, recv_window=None))
  return o['quantity'], o['price']


def nado() -> tuple[Any, Any]:
  """Nado's signed order struct, in x18 integers."""
  from tribulnation.nado.market.orders import nado_order

  o = nado_order(ORDER)
  return Decimal(o['amount']) / 10**18, Decimal(o['priceX18']) / 10**18


def risex() -> tuple[Any, Any]:
  """RISEx's request in whole steps of `0.000001` and ticks of `0.1`."""
  from typed_risex.markets.all import MarketInfo
  from tribulnation.risex.market.orders import order_request

  row: dict[str, Any] = {
    'market_id': 1,
    'config': {
      'name': 'BTC/USDC',
      'step_size': Decimal('0.000001'),
      'step_price': Decimal('0.1'),
    },
  }
  o = order_request(cast(MarketInfo, row), ORDER)
  return o['size_steps'] * Decimal('0.000001'), o['price_ticks'] * Decimal('0.1')


BUILDERS: list[Callable[[], tuple[Any, Any]]] = [
  aster,
  bit2me,
  bybit,
  coinbase,
  dydx,
  grvt,
  hyperliquid,
  margin_trade,
  mexc,
  nado,
  risex,
]


@pytest.mark.parametrize('build', BUILDERS, ids=lambda f: f.__name__)
def test_float_order_inputs_keep_their_decimal_digits(
  build: Callable[[], tuple[Any, Any]],
):
  """The payload carries exactly `0.1` and `2345.6`, and no grid check refuses them."""
  qty, price = build()
  assert (Decimal(qty), Decimal(price)) == (QTY, PRICE)
