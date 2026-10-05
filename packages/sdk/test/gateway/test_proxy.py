from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing_extensions import Any, Sequence
import asyncio
import os

import pytest
import pytest_asyncio
from aiohttp import web

from tribulnation.sdk.gateway import codec
from tribulnation.sdk.gateway.proxy import ProxySDK
from tribulnation.sdk.gateway.server import Gateway
from tribulnation.sdk import ApiError, NetworkError
from tribulnation.sdk.core import PaginatedResponse, OverflowPolicy
from tribulnation.sdk.market import (
  Book,
  Fees,
  NextFunding,
  PerpCollateral,
  FundingPayment,
  FundingRate,
  Order,
  OrderResponse,
  OrderState,
  PerpMarket,
  PerpPosition,
  Position,
  Rules,
  Settings,
  Trade,
  TradingMarkets,
)
from tribulnation.sdk.market.exchange import PerpExchange
from tribulnation.sdk.market.venue import ExchangeDescription, TradingVenue


MARKET_ID = 'mock:perp:BTC-USD'


@dataclass
class MockState:
  depth_error: Exception | None = None
  depth_stream_items: list[Book | Exception] = field(default_factory=list)
  depth_stream_wait: bool = False
  depth_stream_started: asyncio.Event = field(default_factory=asyncio.Event)
  depth_stream_unsubscribed: int = 0


def book(price: str = '100') -> Book:
  p = Decimal(price)
  return Book(
    bids=[Book.Entry(price=p - Decimal('1'), qty=Decimal('2'))],
    asks=[Book.Entry(price=p + Decimal('1'), qty=Decimal('3'))],
  )


def rules() -> Rules:
  return Rules(
    fee_asset='USD',
    tick_size=Decimal('0.5'),
    step_size=Decimal('0.001'),
    fees=Fees.symmetric(maker=Decimal('0.0001'), taker=Decimal('0.0005')),
    api=True,
  )


@dataclass
class MockMarket(PerpMarket):
  state: MockState

  @property
  def venue_id(self) -> str:
    return 'mock'

  @property
  def exchange_id(self) -> str:
    return 'perp'

  @property
  def market_id(self) -> str:
    return 'BTC-USD'

  async def depth(self, *, levels: int | None = None) -> Book:
    if self.state.depth_error is not None:
      raise self.state.depth_error
    b = book()
    return b.limit(levels) if levels is not None else b

  @asynccontextmanager
  async def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ):
    async def gen() -> AsyncIterator[Book]:
      self.state.depth_stream_started.set()
      for item in self.state.depth_stream_items:
        if isinstance(item, Exception):
          raise item
        yield item.limit(levels) if levels is not None else item
      if self.state.depth_stream_wait:
        await asyncio.Event().wait()

    try:
      yield gen()
    finally:
      self.state.depth_stream_unsubscribed += 1

  async def rules(self, *, refetch: bool = False) -> Rules:
    return rules()

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Provide account rates distinct from the public schedule."""
    return Fees(
      maker_buy=Decimal('0.001'),
      maker_sell=Decimal('0.002'),
      taker_buy=Decimal('0.003'),
      taker_sell=Decimal('0.004'),
    )

  def candles(self, interval, start, end):
    """Provide an empty fixture candle window."""

    async def pages():
      """Yield one empty historical page."""
      yield []

    return PaginatedResponse(pages())

  async def perp_collateral(self) -> PerpCollateral:
    """Provide a cross-margin collateral fixture."""
    return PerpCollateral(
      equity=Decimal(100),
      free_collateral=Decimal(80),
      initial_margin=Decimal(20),
      maintenance_margin=Decimal(10),
      leverage=Decimal(2),
      margin_mode='cross',
    )

  async def open_orders(self) -> Sequence[OrderState]:
    return []

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    async def gen() -> AsyncIterator[Sequence[Trade]]:
      yield []

    return PaginatedResponse(gen())

  @asynccontextmanager
  async def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    async def gen() -> AsyncIterator[Trade]:
      return
      yield

    yield gen()

  async def position(self) -> Position:
    return Position()

  async def available_notional(self) -> Decimal:
    return Decimal('1000')

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    return OrderResponse(id='order-1')

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    return {'cancelled': id}

  async def index(self, *, settings: Settings = {}) -> Decimal:
    return Decimal('100')

  async def next_funding(self) -> NextFunding:
    return NextFunding(
      rate=Decimal('0.001'),
      time=datetime.now(timezone.utc),
      interval=timedelta(hours=1),
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    async def gen() -> AsyncIterator[Sequence[FundingRate]]:
      yield []

    return PaginatedResponse(gen())

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    async def gen() -> AsyncIterator[Sequence[FundingPayment]]:
      yield []

    return PaginatedResponse(gen())

  async def perp_position(self) -> PerpPosition:
    return PerpPosition()


@dataclass
class MockExchange(PerpExchange):
  state: MockState

  async def tickers(self, markets=None, *, settings={}):
    """Provide an empty bulk ticker snapshot."""
    return {}

  async def perp_stats(self, markets=None, *, settings={}):
    """Provide an empty bulk statistics snapshot."""
    return {}

  async def perp_collateral(self, market_id=None):
    """Provide the exchange bucket used by the mock market."""
    return await MockMarket(self.state).perp_collateral()

  @property
  def venue_id(self) -> str:
    return 'mock'

  @property
  def exchange_id(self) -> str:
    return 'perp'

  async def market(self, market_id: str, /) -> PerpMarket:
    assert market_id == 'BTC-USD'
    return MockMarket(self.state)

  async def markets(self) -> Sequence[str]:
    return ['BTC-USD']


@dataclass
class MockVenue(TradingVenue):
  state: MockState

  @property
  def venue_id(self) -> str:
    return 'mock'

  async def exchange(self, exchange_id: str, /) -> MockExchange:
    assert exchange_id == 'perp'
    return MockExchange(self.state)

  async def perp_exchange(self, exchange_id: str, /) -> MockExchange:
    return await self.exchange(exchange_id)

  async def exchanges(self) -> Sequence[ExchangeDescription]:
    return [{'id': 'perp', 'type': 'perp', 'name': 'Perpetuals'}]


@dataclass
class MockSDK(TradingMarkets):
  state: MockState

  async def venues(self) -> Sequence[str]:
    return ['mock']

  async def venue(self, id: str, /) -> TradingVenue:
    assert id == 'mock'
    return MockVenue(self.state)


class FakeWebSocket:
  closed = False

  def __init__(self):
    self.sent: list[codec.ServerMsg] = []

  async def send_bytes(self, data: bytes) -> None:
    self.sent.append(codec.decode_server(data))


@dataclass
class WaitingMarket(MockMarket):
  started: asyncio.Event = field(default_factory=asyncio.Event)

  @asynccontextmanager
  async def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ):
    async def gen() -> AsyncIterator[Book]:
      self.started.set()
      await asyncio.Event().wait()
      yield book().limit(levels) if levels is not None else book()

    yield gen()


class WaitingGateway(Gateway):
  def __init__(self, sdk: TradingMarkets, market: WaitingMarket):
    super().__init__(sdk)
    self.market = market

  async def _market(self, market_id: str) -> PerpMarket:
    assert market_id == MARKET_ID
    return self.market


@pytest_asyncio.fixture
async def mock_state() -> MockState:
  return MockState()


@pytest_asyncio.fixture
async def gateway_url(mock_state: MockState, tmp_path: Path) -> AsyncIterator[str]:
  socket_path = tmp_path / 'gateway.sock'
  gateway = Gateway(MockSDK(mock_state))  # type: ignore[arg-type]
  app = web.Application()
  app.router.add_get('/', gateway.handler)

  runner = web.AppRunner(app, shutdown_timeout=1.0)
  await runner.setup()
  await web.UnixSite(runner, str(socket_path)).start()
  try:
    yield f'unix://{socket_path}'
  finally:
    await runner.cleanup()
    try:
      os.unlink(socket_path)
    except FileNotFoundError:
      pass


@pytest_asyncio.fixture
async def sdk(gateway_url: str) -> AsyncIterator[ProxySDK]:
  async with ProxySDK.at(gateway_url) as proxy:
    yield proxy


@pytest.mark.asyncio
async def test_unary_success_routes_through_gateway(sdk: ProxySDK) -> None:
  assert await sdk.venues() == ['mock']
  venue = await sdk.venue('mock')
  assert await venue.exchanges() == [
    {'id': 'perp', 'type': 'perp', 'name': 'Perpetuals'}
  ]

  market = await sdk.perp_market(MARKET_ID)
  b = await market.depth(levels=1)

  assert b.best_bid.price == Decimal('99')
  assert b.best_ask.price == Decimal('101')


@pytest.mark.asyncio
async def test_unary_error_raises_and_clears_pending(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  mock_state.depth_error = ApiError('depth boom')
  market = await sdk.perp_market(MARKET_ID)

  with pytest.raises(ApiError, match='depth boom'):
    await market.depth()

  ctx = await sdk._conn.ctx
  assert ctx.pending == {}


@pytest.mark.asyncio
async def test_depth_stream_clean_completion(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  mock_state.depth_stream_items = [book('100'), book('110')]
  market = await sdk.perp_market(MARKET_ID)

  async with market.depth_stream(queue_size=10, overflow='fail') as stream:
    received = [item async for item in stream]

  assert [b.best_bid.price for b in received] == [Decimal('99'), Decimal('109')]
  assert mock_state.depth_stream_unsubscribed == 1
  ctx = await sdk._conn.ctx
  assert ctx.subs == {}


@pytest.mark.asyncio
async def test_depth_stream_failure_raises_without_background_task_error(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  event_loop = asyncio.get_running_loop()
  loop_errors: list[dict[str, object]] = []
  previous_handler = event_loop.get_exception_handler()
  event_loop.set_exception_handler(lambda loop, context: loop_errors.append(context))
  mock_state.depth_stream_items = [book('100'), NetworkError('stream boom')]
  market = await sdk.perp_market(MARKET_ID)

  try:
    async with market.depth_stream() as stream:
      items = aiter(stream)

      first = await anext(items)
      assert first.best_bid.price == Decimal('99')
      with pytest.raises(NetworkError, match='stream boom'):
        await anext(items)

    assert mock_state.depth_stream_unsubscribed == 1
    assert not loop_errors
  finally:
    event_loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_depth_stream_unsubscribe_clears_server_subscription(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  mock_state.depth_stream_items = [book('100')]
  mock_state.depth_stream_wait = True
  market = await sdk.perp_market(MARKET_ID)

  async with market.depth_stream() as stream:
    items = aiter(stream)
    assert (await anext(items)).best_bid.price == Decimal('99')
    # exiting the `async with` block below unsubscribes

  await asyncio.wait_for(mock_state.depth_stream_started.wait(), timeout=1)
  for _ in range(10):
    if mock_state.depth_stream_unsubscribed:
      break
    await asyncio.sleep(0)

  assert mock_state.depth_stream_unsubscribed == 1
  ctx = await sdk._conn.ctx
  assert ctx.subs == {}


@pytest.mark.asyncio
async def test_stream_and_unary_call_multiplex_on_one_connection(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  mock_state.depth_stream_items = [book('120')]
  market = await sdk.perp_market(MARKET_ID)

  async with market.depth_stream() as stream:
    depth_task = asyncio.create_task(market.depth())
    stream_item = await anext(aiter(stream))
    unary_book = await depth_task

  assert stream_item.best_bid.price == Decimal('119')
  assert unary_book.best_bid.price == Decimal('99')


@pytest.mark.asyncio
async def test_connection_reconnects_after_recv_loop_dies(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  market = await sdk.perp_market(MARKET_ID)
  assert (await market.depth()).best_bid.price == Decimal('99')

  ctx = await sdk._conn.ctx
  ctx.recv_task.cancel()
  with pytest.raises(asyncio.CancelledError):
    await ctx.recv_task

  assert sdk._conn._ctx is None

  assert (await market.depth()).best_bid.price == Decimal('99')
  new_ctx = await sdk._conn.ctx
  assert new_ctx is not ctx


def test_exception_codec_roundtrip() -> None:
  exc_cls = codec.decode_exception(codec.encode_exception(ApiError('boom')))
  exc = exc_cls('boom')

  assert isinstance(exc, ApiError)
  assert str(exc) == 'ApiError(boom)'


def test_error_messages_share_exception_field_shape() -> None:
  encoded_err = codec.encode_server(
    codec.ErrMsg(id='call-1', error='boom', exc='ApiError')
  )
  encoded_end = codec.encode_server(
    codec.EndMsg(id='stream-1', error='boom', exc='NetworkError')
  )

  err = codec.decode_server(encoded_err)
  end = codec.decode_server(encoded_end)

  assert isinstance(err, codec.ErrMsg)
  assert isinstance(end, codec.EndMsg)
  assert err.exc == 'ApiError'
  assert end.exc == 'NetworkError'


@pytest.mark.asyncio
async def test_cancelled_gateway_stream_does_not_send_end() -> None:
  market = WaitingMarket(MockState())
  gateway = WaitingGateway(MockSDK(MockState()), market=market)  # type: ignore[arg-type]
  ws = FakeWebSocket()
  req = codec.DepthStreamReq(id='stream-1', market_id=MARKET_ID)
  sub_tasks: dict[str, asyncio.Task] = {}

  task = asyncio.create_task(gateway._stream(ws, req, sub_tasks))  # type: ignore
  sub_tasks[req.id] = task
  await asyncio.wait_for(market.started.wait(), timeout=1)
  task.cancel()
  await task

  assert ws.sent == []
  assert sub_tasks == {}


@pytest.mark.asyncio
async def test_sdk2_account_fees_and_funding_interval(sdk: ProxySDK):
  """Preserve side-specific rates and the next settlement interval over RPC."""
  fees = await sdk.fees(MARKET_ID)
  assert fees.maker_buy == Decimal('0.001')
  assert fees.taker_sell == Decimal('0.004')
  funding = await sdk.next_funding(MARKET_ID)
  assert funding.interval == timedelta(hours=1)
  assert funding.annualized == Decimal('8.760')
  assert await sdk.funding_rates(MARKET_ID) == []
  assert (await sdk.collateral('mock:perp')).maintenance_ratio == Decimal('0.1')
