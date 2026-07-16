from decimal import Decimal

from tribulnation.dydx.market.impl.orders import export_order


def test_dydx_market_orders_default_to_ioc():
  order = export_order(
    {'type': 'MARKET', 'qty': Decimal('1'), 'price': Decimal('100')},
    {},
  )

  assert order['time_in_force'] == 'IMMEDIATE_OR_CANCEL'


def test_dydx_market_tif_can_be_overridden():
  order = export_order(
    {'type': 'MARKET', 'qty': Decimal('1'), 'price': Decimal('100')},
    {'market_tif': 'FILL_OR_KILL'},
  )

  assert order['time_in_force'] == 'FILL_OR_KILL'


def test_dydx_limit_orders_keep_good_til_time_default():
  order = export_order(
    {'type': 'LIMIT', 'qty': Decimal('1'), 'price': Decimal('100')},
    {},
  )

  assert order['time_in_force'] == 'GOOD_TIL_TIME'
