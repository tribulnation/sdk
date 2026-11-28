"""Orders built from SDK orders, refusals, cancellation, lookup and open orders."""

from decimal import Decimal

import pytest

from tribulnation.evedex.core import ORDER_ID, random_client_order_id
from tribulnation.evedex.market.markets import EvedexPerpMarket
from tribulnation.sdk.core import AuthError, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order

from .conftest import BUY_ID, SELL_ID, Fake, order, position, refusal


def market(fake: Fake, **kwargs: bool) -> EvedexPerpMarket:
  """XRPUSD over the fake client."""
  return EvedexPerpMarket(shared=fake.shared(**kwargs), name='XRPUSD')


def placements(fake: Fake) -> list[dict[str, object]]:
  """The keyword arguments of every `place_limit` call."""
  return [kwargs for name, kwargs in fake.calls if name == 'place_limit']


async def test_each_order_type_is_a_limit_at_the_account_leverage(fake: Fake):
  """`LIMIT` is GTC, `MARKET` is an IOC limit; sells are `SELL` with an unsigned
  quantity, all at the position record's leverage."""
  fake.positions = [position(leverage=3)]
  m = market(fake)
  await m.place_order({'type': 'LIMIT', 'qty': '6', 'price': '0.95'})
  await m.place_order({'type': 'LIMIT', 'qty': Decimal('-6.5'), 'price': '1.01'})
  await m.place_order({'type': 'MARKET', 'qty': '6', 'price': '0.9999'})
  limit, sell, ioc = placements(fake)
  assert limit['side'] == 'BUY' and limit['quantity'] == Decimal('6')
  assert limit['time_in_force'] is None and 'post_only' not in limit
  assert limit['leverage'] == 3
  assert sell['side'] == 'SELL' and sell['quantity'] == Decimal('6.5')
  assert ioc['time_in_force'] == 'IOC' and ioc['limit_price'] == Decimal('0.9999')


async def test_unset_leverage_is_the_venue_default(fake: Fake):
  """An instrument with no position record trades at leverage 1."""
  fake.positions = []
  await market(fake).place_order({'type': 'LIMIT', 'qty': '6', 'price': '0.95'})
  assert placements(fake)[0]['leverage'] == 1


async def test_orders_reuse_the_stored_leverage(fake: Fake):
  """Only the first order reads the positions for its leverage; `set_leverage` and a
  refusal drop the stored answer, so the next order reads the setting afresh."""
  fake.positions = [position(leverage=3)]
  m = market(fake)
  buy: Order = {'type': 'LIMIT', 'qty': '6', 'price': '0.95'}
  await m.place_order(buy)
  await m.place_order(buy)
  assert fake.positions_reads == 1
  await m.set_leverage(Decimal(2))
  fake.positions = [position(leverage=2)]
  await m.place_order(buy)
  assert fake.positions_reads == 2 and placements(fake)[-1]['leverage'] == 2
  fake.error = refusal(400, 'mark_price_limit_exceeded_error')
  with pytest.raises(OrderRejected):
    await m.place_order(buy)
  fake.positions = [position(leverage=5)]
  await m.place_order(buy)
  assert fake.positions_reads == 3 and placements(fake)[-1]['leverage'] == 5


async def test_client_order_ids_are_the_order_ids(fake: Fake):
  """A client order id is sent as the order's id and must have the venue's form."""
  m = market(fake)
  cid = m.random_client_order_id()
  assert ORDER_ID.match(cid) and ORDER_ID.match(random_client_order_id())
  response = await m.place_order(
    {'type': 'LIMIT', 'qty': '6', 'price': '0.95', 'client_order_id': cid}
  )
  assert placements(fake)[0]['id'] == cid
  assert response.id == BUY_ID and response.filled_qty is None
  with pytest.raises(ValueError):
    await m.place_order(
      {'type': 'LIMIT', 'qty': '6', 'price': '0.95', 'client_order_id': '42'}
    )


@pytest.mark.parametrize(
  ('qty', 'price'), [('0', '0.95'), ('6', '0'), ('6.05', '0.95'), ('6', '0.95001')]
)
async def test_invalid_orders_raise_before_signing(fake: Fake, qty: str, price: str):
  """Zero size, a non-positive price and off-grid values never reach the client."""
  with pytest.raises(ValueError):
    await market(fake).place_order({'type': 'LIMIT', 'qty': qty, 'price': price})
  assert placements(fake) == []


async def test_orders_need_the_wallet(fake: Fake):
  """An API key alone reads but cannot sign."""
  with pytest.raises(AuthError):
    await market(fake, wallet=False).place_order(
      {'type': 'LIMIT', 'qty': '6', 'price': '0.95'}
    )


async def test_refusals_are_rejections(fake: Fake):
  """A labelled `4xx` and a `REJECTED` reply both mean nothing rests."""
  m = market(fake)
  fake.error = refusal(400, 'mark_price_limit_exceeded_error')
  with pytest.raises(OrderRejected):
    await m.place_order({'type': 'LIMIT', 'qty': '6', 'price': '0.5'})
  fake.placed = order(id=BUY_ID, status='REJECTED', rejectedReason='no margin')
  with pytest.raises(OrderRejected):
    await m.place_order({'type': 'LIMIT', 'qty': '6', 'price': '0.95'})


async def test_cancelling_an_unknown_order(fake: Fake):
  """`order_not_found_error` is `OrderNotFound`; other refusals stay `BadRequest`."""
  m = market(fake)
  assert await m.cancel_order(SELL_ID) == {}
  fake.error = refusal(404, 'order_not_found_error')
  with pytest.raises(OrderNotFound):
    await m.cancel_order(SELL_ID)
  await m.cancel_open_orders()
  assert ('cancel_by_instrument', 'XRPUSD') in fake.calls


async def test_query_order_open_or_closed(fake: Fake):
  """A filled sell is inactive and fully filled; other instruments and unknown ids are
  `None`."""
  m = market(fake)
  state = await m.query_order(SELL_ID)
  assert state is not None and not state.active
  assert state.qty == Decimal('-6') and state.filled_qty == Decimal('-6')
  fake.orders = [order(instrument='BTCUSD')]
  assert await m.query_order(SELL_ID) is None
  fake.error = refusal(404, 'order_not_found_error')
  assert await m.query_order(SELL_ID) is None


async def test_open_orders_of_one_instrument(fake: Fake):
  """Open orders of other instruments are left out; fill progress is kept."""
  fake.opened = [
    order(
      id=BUY_ID, side='BUY', status='PARTIALLY_FILLED', unFilledQuantity=Decimal('2')
    ),
    order(instrument='BTCUSD', status='NEW'),
  ]
  [state] = await market(fake).open_orders()
  assert state.id == BUY_ID and state.active
  assert state.qty == Decimal('6') and state.filled_qty == Decimal('4')


async def test_set_leverage_checks_the_maximum(fake: Fake):
  """Whole numbers up to `maxLeverage`; the next read is fresh."""
  m = market(fake)
  await m.set_leverage(Decimal(2))
  assert ('set_leverage', ('XRPUSD', 2)) in fake.calls
  for bad in (Decimal('2.5'), Decimal(101), Decimal(0)):
    with pytest.raises(ValueError):
      await m.set_leverage(bad)


async def test_post_only_is_refused_before_anything_is_sent(fake: Fake):
  """The venue refuses `postOnly`, so `POST_ONLY` raises before signing, and a
  `POST_ONLY` replacement before cancelling the order it would replace."""
  m = market(fake)
  post: Order = {'type': 'POST_ONLY', 'qty': '6', 'price': '0.95'}
  with pytest.raises(NotImplementedError):
    await m.place_order(post)
  with pytest.raises(NotImplementedError):
    await m.replace_order(SELL_ID, post)
  assert fake.calls == []


async def test_rules_bound_prices_by_the_mark_band(fake: Fake):
  """`markPriceLimit` either side of the mark; the absolute range stays in details."""
  rules = await market(fake, keyed=False).rules()
  assert rules.rel_min_price == Decimal('0.7') and rules.rel_max_price == Decimal('1.3')
  assert rules.min_value == 5 and rules.details['minPrice'] == Decimal('0.1973')
