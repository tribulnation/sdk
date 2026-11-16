"""Trading a Bitget USDT-margined perpetual on a Unified Trading Account, end to end
against the fake venue in `conftest.py`."""

from typing_extensions import TYPE_CHECKING, Any, AsyncIterator, cast
from decimal import Decimal

import pytest

from tribulnation.sdk.core import ApiError, NetworkError, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Settings
from tribulnation.bitget.market.impl import merged_books
from tribulnation.bitget.market.perp_market import PerpMarket
from typed_bitget.classic_streams.orderbook import OrderBookPush

if TYPE_CHECKING:
  from conftest import FakeBitget

IOC: Settings = {'bitget': {'time_in_force': 'ioc'}}
NOW_TS = None
"""Push timestamps, which folding never reads."""


def placed(fake: 'FakeBitget') -> list[dict[str, Any]]:
  """The bodies of every `place-order` request so far."""
  return [p for _, e, p in fake.requests if e == 'trade/place-order']


async def test_an_ioc_limit_fills_against_the_book_and_reports_its_fill(
  fake: 'FakeBitget', market: PerpMarket
):
  """The hedger's order: a `LIMIT` with the IOC setting, on cross margin, its fill
  read back at once because Bitget's placement answers only the ID."""
  r = await market.place_order(
    {'type': 'LIMIT', 'qty': Decimal(-2500), 'price': Decimal('0.0024')},
    settings=IOC,
  )
  [body] = placed(fake)
  assert body['side'] == 'sell' and Decimal(body['qty']) == 2500
  assert body['timeInForce'] == 'ioc' and body['marginMode'] == 'crossed'
  assert r.filled_qty == 2500
  assert fake.position == -2500
  assert (await market.position()).size == -2500


async def test_a_market_order_is_an_ioc_bounded_by_its_price_and_may_fill_partly(
  fake: 'FakeBitget', market: PerpMarket
):
  """`MARKET` is an IOC limit at the order's price; what the book lacks is cancelled."""
  fake.depth = Decimal(1000)
  r = await market.place_order(
    {'type': 'MARKET', 'qty': Decimal(3000), 'price': Decimal('0.00245')}
  )
  assert placed(fake)[0]['timeInForce'] == 'ioc'
  assert r.filled_qty == 1000
  state = await market.query_order(r.id)
  assert state is not None and not state.active and state.filled_qty == 1000


async def test_an_ioc_that_misses_the_book_reports_nothing_filled(
  fake: 'FakeBitget', market: PerpMarket
):
  """An IOC with nothing to match is accepted and cancelled, not refused."""
  r = await market.place_order(
    {'type': 'LIMIT', 'qty': Decimal(2500), 'price': Decimal('0.0023')}, settings=IOC
  )
  assert r.filled_qty == 0


async def test_a_post_only_rests_is_listed_and_cancelled(
  fake: 'FakeBitget', market: PerpMarket
):
  """A resting maker order: listed, queried active, cancelled; a second cancel is
  `OrderNotFound`, as the base `replace_order` expects."""
  r = await market.place_order(
    {
      'type': 'POST_ONLY',
      'qty': Decimal(2500),
      'price': Decimal('0.0020'),
      'client_order_id': market.random_client_order_id(),
    }
  )
  body = placed(fake)[0]
  assert body['timeInForce'] == 'post_only' and len(body['clientOid']) == 32
  assert r.filled_qty is None
  [listed] = await market.open_orders()
  assert listed.id == r.id and listed.qty == 2500
  state = await market.query_order(r.id)
  assert state is not None and state.active
  await market.cancel_order(r.id)
  state = await market.query_order(r.id)
  assert state is not None and not state.active
  with pytest.raises(OrderNotFound):
    await market.cancel_order(r.id)


async def test_a_post_only_that_would_cross_does_not_take(
  fake: 'FakeBitget', market: PerpMarket
):
  """Bitget cancels a crossing post-only instead of matching it."""
  r = await market.place_order(
    {'type': 'POST_ONLY', 'qty': Decimal(2500), 'price': Decimal('0.0025')}
  )
  state = await market.query_order(r.id)
  assert state is not None and not state.active and state.filled_qty == 0
  assert fake.position == 0


async def test_an_unknown_order_queries_as_none(market: PerpMarket):
  """Bitget's `25204` (order does not exist) is no order, not an error."""
  assert await market.query_order('42') is None


async def test_an_unfilled_order_is_modified_in_place(
  fake: 'FakeBitget', market: PerpMarket
):
  """`replace_order` uses `modify-order` (auto-cancelling on failure) and returns the
  ID Bitget answers."""
  r = await market.place_order(
    {'type': 'POST_ONLY', 'qty': Decimal(2500), 'price': Decimal('0.0020')}
  )
  new = await market.replace_order(
    r.id, {'type': 'POST_ONLY', 'qty': Decimal(3000), 'price': Decimal('0.0021')}
  )
  [(_, _, modify)] = [x for x in fake.requests if x[1] == 'trade/modify-order']
  assert modify['autoCancel'] == 'yes' and Decimal(modify['qty']) == 3000
  assert new.id != r.id
  [listed] = await market.open_orders()
  assert listed.id == new.id and listed.price == Decimal('0.0021')


async def test_a_partly_filled_order_is_cancelled_and_placed_anew(
  fake: 'FakeBitget', market: PerpMarket
):
  """Bitget's modified `qty` counts the filled part, so a partly filled order is
  replaced by cancel and place rather than modified."""
  r = await market.place_order(
    {'type': 'LIMIT', 'qty': Decimal(5000), 'price': Decimal('0.0020')}
  )
  fake.execute(fake.orders[r.id], Decimal(1000))
  new = await market.replace_order(
    r.id, {'type': 'LIMIT', 'qty': Decimal(4000), 'price': Decimal('0.0021')}
  )
  assert not any(e == 'trade/modify-order' for _, e, _ in fake.requests)
  assert fake.orders[r.id].status == 'cancelled'
  [listed] = await market.open_orders()
  assert listed.id == new.id and listed.qty == 4000


async def test_cancel_open_orders_cancels_the_symbol_in_one_request(
  fake: 'FakeBitget', market: PerpMarket
):
  """One `cancel-symbol-order` request, scoped to this symbol."""
  for price in ('0.0020', '0.0021'):
    await market.place_order(
      {'type': 'POST_ONLY', 'qty': Decimal(2500), 'price': Decimal(price)}
    )
  await market.cancel_open_orders()
  [(_, _, body)] = [x for x in fake.requests if x[1] == 'trade/cancel-symbol-order']
  assert body == {'category': 'USDT-FUTURES', 'symbol': 'IOTXUSDT'}
  assert await market.open_orders() == []


async def test_a_definitive_refusal_is_order_rejected(
  fake: 'FakeBitget', market: PerpMarket
):
  """Insufficient balance places nothing: `OrderRejected`, safe to re-send."""
  fake.reject_code = '43012'
  with pytest.raises(OrderRejected):
    await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(2500), 'price': Decimal('0.0024')}
    )


async def test_an_unknown_error_stays_ambiguous(fake: 'FakeBitget', market: PerpMarket):
  """A code not known to refuse outright may have placed: a plain `ApiError`."""
  fake.reject_code = '50000'
  with pytest.raises(ApiError) as e:
    await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(2500), 'price': Decimal('0.0024')}
    )
  assert not isinstance(e.value, OrderRejected)


async def test_leverage_is_the_symbols_cross_setting(
  fake: 'FakeBitget', market: PerpMarket
):
  """The cross row of `account.settings`; an isolated row is not it."""
  fake.symbol_configs.insert(
    0,
    {
      'category': 'USDT-FUTURES',
      'symbol': 'IOTXUSDT',
      'marginMode': 'isolated',
      'leverage': '10',
    },
  )
  assert await market.leverage() == 5


async def test_a_symbol_without_a_leverage_setting_raises(
  fake: 'FakeBitget', market: PerpMarket
):
  """Bitget lists no row until leverage is set; guessing its default could under-hold."""
  fake.symbol_configs.clear()
  with pytest.raises(ValueError, match='No cross leverage'):
    await market.leverage()


async def test_the_pool_funds_orders_and_its_free_part_excludes_margin_in_use(
  market: PerpMarket,
):
  """Free collateral is effective equity less initial margin; holds are drawn on the
  unified pool's ID at the symbol's leverage."""
  collateral = await market.collateral()
  assert collateral.free_collateral == 800 and collateral.margin_mode == 'cross'
  assert await market.collateral_id() == 'bg:usdt'
  hold = await market.hold(qty=Decimal(10000), price=Decimal('0.0025'))
  assert hold.collateral_id == 'bg:usdt' and hold.amount == 5


async def test_a_classic_account_does_not_trade(
  fake: 'FakeBitget', classic_market: PerpMarket
):
  """Classic futures trading is not implemented: nothing is sent."""
  market = classic_market
  with pytest.raises(NotImplementedError):
    await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(2500), 'price': Decimal('0.0024')}
    )
  assert placed(fake) == []


def push(
  action: str, seq: int, pseq: int, bids: list[tuple[str, str]]
) -> OrderBookPush:
  """One futures `books` push."""
  levels: dict[str, Any] = {
    'bids': [(Decimal(p), Decimal(q)) for p, q in bids],
    'asks': [(Decimal('0.0025'), Decimal(100))],
    'ts': NOW_TS,
    'seq': seq,
    'pseq': pseq,
  }
  frame: dict[str, Any] = {
    'action': action,
    'arg': {'instType': 'USDT-FUTURES', 'channel': 'books', 'instId': 'IOTXUSDT'},
    'data': [levels],
    'ts': NOW_TS,
  }
  return cast(OrderBookPush, frame)


async def replay(*frames: OrderBookPush) -> AsyncIterator[OrderBookPush]:
  """Replay pushes."""
  for frame in frames:
    yield frame


async def test_chained_futures_updates_fold_into_the_book():
  """Each update's `pseq` is the previous `seq` (as observed live)."""
  books = [
    b
    async for b in merged_books(
      replay(
        push('snapshot', 10, 0, [('0.0024', '5')]),
        push('update', 17, 10, [('0.0024', '0'), ('0.00241', '7')]),
        push('update', 30, 17, [('0.00239', '1')]),
      )
    )
  ]
  assert [(e.price, e.qty) for e in books[-1].bids] == [
    (Decimal('0.00241'), 7),
    (Decimal('0.00239'), 1),
  ]


async def test_a_lost_futures_update_fails_the_stream():
  """A broken `pseq` chain is a lost update: the stream fails rather than serve a
  wrong book, and a resubscribe starts from a fresh snapshot."""
  with pytest.raises(NetworkError, match='out of sequence'):
    async for _ in merged_books(
      replay(
        push('snapshot', 10, 0, [('0.0024', '5')]),
        push('update', 30, 17, [('0.00239', '1')]),
      )
    ):
      pass
