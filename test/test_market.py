"""Live market conformance tests for `TradingSDK` markets."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import asyncio

from typing_extensions import Literal
import pytest

from tribulnation.sdk import TradingSDK
from tribulnation.sdk.core import Stream
from tribulnation.sdk.market import Book, Market, PerpMarket, Order, Rules

from conftest import load_venue_env

Side = Literal['buy', 'sell']

@dataclass(frozen=True)
class MarketTestPlan:
  """Live-market test parameters that cannot be inferred safely."""
  venue: str
  market_id: str
  required_env: tuple[str, ...]
  order_notional: Decimal
  fill_notional: Decimal
  side: Side = 'buy'
  history_window: timedelta = timedelta(days=7)
  stream_timeout: float = 15.0


PLANS = [
  MarketTestPlan(
    venue='hyperliquid',
    market_id='hyperliquid_testnet::BTC',
    required_env=('HYPERLIQUID_TESTNET_ADDRESS', 'HYPERLIQUID_TESTNET_PRIVATE_KEY'),
    order_notional=Decimal('50'),
    fill_notional=Decimal('50'),
  ),
  MarketTestPlan(
    venue='dydx',
    market_id='dydx_testnet:perp:BTC-USD',
    required_env=('DYDX_TESTNET_MNEMONIC',),
    order_notional=Decimal('50'),
    fill_notional=Decimal('50'),
  ),
  MarketTestPlan(
    venue='mexc',
    market_id='mexc:spot:BTCUSDT',
    required_env=('MEXC_ACCESS_KEY', 'MEXC_SECRET_KEY'),
    order_notional=Decimal('6'),
    fill_notional=Decimal('6'),
  ),
]

async def first_stream_item(stream: Stream[object], *, timeout: float) -> object:
  """Read one item from a live stream."""
  return await asyncio.wait_for(anext(aiter(stream)), timeout=timeout)


async def optional_stream_item(stream: Stream[object], *, timeout: float) -> object | None:
  """Try to read one item from a live stream without making test success depend on live event timing."""
  try:
    return await first_stream_item(stream, timeout=timeout)
  except TimeoutError:
    return None


def order_qty(rules: Rules, *, notional: Decimal, price: Decimal) -> Decimal:
  """Convert a quote notional into a valid order quantity."""
  qty = rules.amount2qty(notional, price=price)
  if qty is None:
    pytest.skip(f'{rules.base}/{rules.quote} minimum order is above configured test notional')
    raise RuntimeError('unreachable after pytest.skip')
  return qty


def passive_buy_order(rules: Rules, *, book: Book, notional: Decimal) -> Order:
  """Build a buy order intended to rest away from the spread."""
  raw_price = book.best_bid.price * Decimal('0.8')
  min_price = rules.min_price(book.mark_price)
  if min_price is not None:
    raw_price = max(raw_price, min_price)
  price = rules.trunc_price(raw_price)
  return {
    'type': 'POST_ONLY',
    'price': price,
    'qty': order_qty(rules, notional=notional, price=price),
  }


def marketable_order(rules: Rules, *, book: Book, notional: Decimal, side: Side) -> Order:
  """Build a small marketable limit order."""
  if side == 'buy':
    raw_price = book.best_ask.price * Decimal('1.02')
    price = rules.ceil_price(raw_price)
    qty = order_qty(rules, notional=notional, price=price)
  else:
    raw_price = book.best_bid.price * Decimal('0.98')
    price = rules.trunc_price(raw_price)
    qty = -order_qty(rules, notional=notional, price=price)
  return {'type': 'LIMIT', 'price': price, 'qty': qty}


async def assert_order_lifecycle(market: Market, *, plan: MarketTestPlan, rules: Rules, book: Book) -> None:
  """Place, query, and cancel a passive order."""
  order = passive_buy_order(rules, book=book, notional=plan.order_notional)
  response = await market.place_order(order)
  try:
    assert response.id
    await market.query_order(response.id)
    await market.open_orders()
  finally:
    await market.cancel_order(response.id)


async def assert_fill(market: Market, *, plan: MarketTestPlan, rules: Rules, book: Book) -> None:
  """Place a tiny marketable order and flatten it with the opposite side."""
  available = await market.available_notional()
  if available < plan.fill_notional:
    pytest.skip(f'Available notional is below configured fill size for {plan.market_id}')

  first = marketable_order(rules, book=book, notional=plan.fill_notional, side=plan.side)
  first_response = await market.place_order(first)
  assert first_response.id

  refreshed = await market.depth()
  opposite: Side = 'sell' if first['qty'] > 0 else 'buy'
  second = marketable_order(
    rules,
    book=refreshed,
    notional=abs(Decimal(first['qty']) * Decimal(first['price'])),
    side=opposite,
  )
  second_response = await market.place_order(second)
  assert second_response.id


async def test_market(market: Market, plan: MarketTestPlan) -> None:
  """Exercise the full live market interface."""
  end = datetime.now().astimezone()
  start = end - plan.history_window

  book = await market.depth(levels=5)
  assert book.bids
  assert book.asks

  stream = await market.depth_stream(levels=5)
  try:
    await first_stream_item(stream, timeout=plan.stream_timeout)
  finally:
    await stream.unsubscribe()

  rules = await market.rules(refetch=True)
  assert rules.api

  await market.open_orders()
  await market.trades_history(start, end)
  await market.position()
  await market.available_notional()

  if isinstance(market, PerpMarket):
    await market.index()
    await market.next_funding()
    await market.funding_history(start, end)
    await market.funding_payments(start, end)
    await market.perp_position()

  try:
    await assert_order_lifecycle(market, plan=plan, rules=rules, book=book)
    trade_stream = await market.trades_stream()
    try:
      await assert_fill(market, plan=plan, rules=rules, book=book)
      await optional_stream_item(trade_stream, timeout=plan.stream_timeout)
    finally:
      await trade_stream.unsubscribe()
  finally:
    await market.cancel_open_orders()


setattr(test_market, '__test__', False)


@pytest.mark.live
@pytest.mark.trading
@pytest.mark.parametrize('plan', PLANS, ids=[plan.market_id for plan in PLANS])
async def test_trading_sdk_market(plan: MarketTestPlan) -> None:
  """Run live conformance against a market instantiated through `TradingSDK`."""
  load_venue_env(plan.venue, required=plan.required_env)
  market = await TradingSDK().market(plan.market_id)
  async with market:
    await test_market(market, plan)
