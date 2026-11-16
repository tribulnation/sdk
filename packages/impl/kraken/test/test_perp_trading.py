"""Order lifecycle, account reads and feeds of a Kraken perpetual, against an in-memory
Futures venue (`fake_futures`)."""

from datetime import timedelta
from decimal import Decimal
import asyncio
from typing_extensions import Any, Callable

import pytest

from tribulnation.sdk import NetworkError, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Fees, Trade
from tribulnation.kraken.market.impl.perp_streams import fold_futures_books
from tribulnation.kraken.market.perp_exchange import PerpExchange
from tribulnation.kraken.market.perp_market import PerpMarket, next_hour

SYMBOL = 'PF_POPCATUSD'
Venue = tuple[Any, Callable[..., PerpMarket]]
"""The `venue` fixture: the fake venue (`conftest.FakeFutures`) and a market factory."""


@pytest.mark.asyncio
async def test_maker_lifecycle(venue: Venue):
  """Post-only rests, is edited in place, fills as maker on the feed, then is gone."""
  fake, market_on = venue
  market = market_on()
  async with market:
    async with market.trades_stream() as trades:
      placed = await market.place_order(
        {
          'type': 'POST_ONLY',
          'qty': Decimal(-1000),
          'price': Decimal('0.0280'),
          'client_order_id': 'mine-1',
        }
      )
      assert placed.filled_qty is None
      assert fake.requests[-1][2]['orderType'] == 'post'
      (open_order,) = await market.open_orders()
      assert (
        open_order.id == placed.id and open_order.qty == -1000 and open_order.active
      )

      edited = await market.replace_order(
        placed.id,
        {'type': 'POST_ONLY', 'qty': Decimal(-800), 'price': Decimal('0.0279')},
      )
      assert edited.id == placed.id
      assert fake.orders[placed.id].price == Decimal('0.0279')
      assert fake.orders[placed.id].size == 800

      fake.fill_maker(placed.id, Decimal(800))
      trade: Trade = await asyncio.wait_for(anext(aiter(trades)), 5)
    assert trade.qty == -800 and trade.maker and trade.order_id == placed.id
    assert trade.client_order_id == 'mine-1'
    assert trade.fee is not None and trade.fee.asset == 'USD'
    state = await market.query_order(placed.id)
    assert state is not None and not state.active and state.filled_qty == -800
    position = await market.perp_position()
    assert position.size == -800 and position.entry_price == Decimal('0.0279')
    with pytest.raises(OrderNotFound):
      await market.cancel_order(placed.id)


@pytest.mark.asyncio
async def test_taker_ioc(venue: Venue):
  """`MARKET` and IOC `LIMIT` report what filled; one that can't fill is rejected."""
  fake, market_on = venue
  market = market_on()
  async with market:
    taken = await market.place_order(
      {'type': 'MARKET', 'qty': Decimal(500), 'price': Decimal('0.0280')}
    )
    assert taken.filled_qty == 500
    assert fake.requests[-1][2]['orderType'] == 'ioc'
    ioc = await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(-20000), 'price': Decimal('0.0270')},
      settings={'kraken': {'time_in_force': 'ioc'}},
    )
    assert ioc.filled_qty == 10000
    with pytest.raises(OrderRejected):
      await market.place_order(
        {'type': 'MARKET', 'qty': Decimal(10), 'price': Decimal('0.0200')}
      )
    with pytest.raises(OrderRejected):
      await market.place_order(
        {'type': 'POST_ONLY', 'qty': Decimal(10), 'price': Decimal('0.0300')}
      )
    assert (await market.perp_position()).size == 500 - 10000
    assert not await market.open_orders()


@pytest.mark.asyncio
async def test_batches(venue: Venue):
  """Batch placement and cancels answer one result per order."""
  fake, market_on = venue
  market = market_on()
  async with market:
    results = await market.place_orders(
      [
        {'type': 'POST_ONLY', 'qty': Decimal(100), 'price': Decimal('0.0270')},
        {'type': 'POST_ONLY', 'qty': Decimal(100), 'price': Decimal('0.0290')},
        {'type': 'LIMIT', 'qty': Decimal(-100), 'price': Decimal('0.0290')},
      ]
    )
    assert isinstance(results[1], OrderRejected)
    ids = [r.id for r in results if not isinstance(r, Exception)]
    assert len(ids) == 2
    cancelled = await market.cancel_orders([*ids, 'missing'])
    assert cancelled[:2] == ['cancelled', 'cancelled']
    assert isinstance(cancelled[2], OrderNotFound)


@pytest.mark.asyncio
async def test_replace_gone_order_places_afresh(venue: Venue):
  """Editing an order that no longer rests places the replacement."""
  fake, market_on = venue
  market = market_on()
  async with market:
    response = await market.replace_order(
      'gone', {'type': 'POST_ONLY', 'qty': Decimal(5), 'price': Decimal('0.0270')}
    )
    assert response.id in fake.orders


@pytest.mark.asyncio
async def test_account_reads(venue: Venue):
  """Collateral is the flex pool; leverage the retail margin; fees the volume tier."""
  fake, market_on = venue
  market = market_on()
  async with market:
    assert await market.collateral_id() == 'kf:perp'
    collateral = await market.perp_collateral()
    assert collateral.equity == Decimal('1001') and collateral.free_collateral == 976
    assert collateral.margin_mode == 'cross' and collateral.leverage == 0
    assert await market.leverage(ttl=timedelta(minutes=1)) == 20
    assert await market.fees() == Fees(
      maker_buy=Decimal('0.000175'),
      maker_sell=Decimal('0.000175'),
      taker_buy=Decimal('0.00045'),
      taker_sell=Decimal('0.00045'),
    )
    exchange = PerpExchange(shared=market.shared)
    assert (await exchange.perp_collateral()).equity == 1001
  europa = market_on(schedule='europa')
  async with europa:
    assert await europa.leverage() == 10


@pytest.mark.asyncio
async def test_book_stream(venue: Venue):
  """The feed's snapshot and level updates fold into whole books."""
  fake, market_on = venue
  market = market_on()
  async with market:
    async with market.depth_stream(queue_size=10, overflow='fail') as books:
      stream = aiter(books)
      first = await asyncio.wait_for(anext(stream), 5)
      assert first.best_bid.price == Decimal('0.0276')
      assert first.best_ask.price == Decimal('0.0277')
      await anext(stream)
      last = await asyncio.wait_for(anext(stream), 5)
  assert last.best_ask.price == Decimal('0.0278')
  assert last.best_bid.price == Decimal('0.02765') and last.best_bid.qty == 42


@pytest.mark.asyncio
async def test_book_gap_fails_the_stream():
  """A skipped `seq` fails the stream rather than serving a wrong book."""

  async def messages():
    yield {
      'feed': 'book_snapshot',
      'product_id': SYMBOL,
      'seq': 1,
      'timestamp': None,
      'bids': [{'price': Decimal(1), 'qty': Decimal(1)}],
      'asks': [],
    }
    yield {
      'feed': 'book',
      'product_id': SYMBOL,
      'side': 'buy',
      'seq': 3,
      'price': Decimal(1),
      'qty': Decimal(0),
      'timestamp': None,
    }

  books = fold_futures_books(messages(), SYMBOL)  # type: ignore[arg-type]
  await anext(books)
  with pytest.raises(NetworkError):
    await anext(books)


def test_next_hour():
  """Funding settles at the next full hour."""
  from datetime import datetime, timezone

  now = datetime(2026, 11, 16, 10, 59, 59, tzinfo=timezone.utc)
  assert next_hour(now) == datetime(2026, 11, 16, 11, tzinfo=timezone.utc)
