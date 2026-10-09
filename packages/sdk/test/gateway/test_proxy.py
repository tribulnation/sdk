from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing_extensions import Any, Sequence
import asyncio
import json
import os

import pydantic
import pytest
import pytest_asyncio
from aiohttp import web

from tribulnation.sdk.gateway import codec
from tribulnation.sdk.impl.accounts import VenueId
from tribulnation.sdk.gateway.proxy import ProxySDK
from tribulnation.sdk.gateway.server import Gateway
from tribulnation.sdk import ApiError, NetworkError, OrderRejected
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
VENUE: VenueId = 'hyperliquid_testnet'
"""The venue every gateway-side mock object reports."""
ALIAS = 'hl'
"""An account key that differs from the venue (`VENUE`) it is configured with."""
ALIAS_MARKET_ID = f'{ALIAS}:perp:BTC-USD'


@dataclass
class MockState:
  depth_error: Exception | None = None
  place_order_error: Exception | None = None
  depth_stream_items: list[Book | Exception] = field(default_factory=list)
  depth_stream_wait: bool = False
  depth_stream_started: asyncio.Event = field(default_factory=asyncio.Event)
  depth_stream_unsubscribed: int = 0
  depth_settings: list[Settings] = field(default_factory=list[Settings])
  """The `settings` every `depth`/`depth_stream` call received, in call order."""
  trades_settings: list[Settings] = field(default_factory=list[Settings])
  """The `settings` every `trades_stream` call received, in call order."""
  trades_stream_items: list[Trade] = field(default_factory=list[Trade])
  """What every `trades_stream` yields."""


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
  def venue_id(self) -> VenueId:
    return VENUE

  @property
  def account_id(self) -> str:
    return 'mock'

  @property
  def exchange_id(self) -> str:
    return 'perp'

  @property
  def market_id(self) -> str:
    return 'BTC-USD'

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    self.state.depth_settings.append(settings)
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
    settings: Settings = {},
  ):
    self.state.depth_settings.append(settings)
    source = settings.get('hyperliquid', {}).get('depth_source')
    items = (
      self.state.depth_stream_items
      if source is None
      else [book('200')] * len(self.state.depth_stream_items)
    )

    async def gen() -> AsyncIterator[Book]:
      self.state.depth_stream_started.set()
      for item in items:
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

  async def leverage(self, *, refetch: bool = False) -> Decimal:
    """Report a refetched setting distinct from the cached one."""
    return Decimal('4') if refetch else Decimal('5')

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
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ):
    self.state.trades_settings.append(settings)
    items = list(self.state.trades_stream_items)

    async def gen() -> AsyncIterator[Trade]:
      for item in items:
        yield item

    yield gen()

  async def position(self) -> Position:
    return Position()

  async def available_notional(self) -> Decimal:
    return Decimal('1000')

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    if self.state.place_order_error is not None:
      raise self.state.place_order_error
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
  def venue_id(self) -> VenueId:
    return VENUE

  @property
  def account_id(self) -> str:
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
  def venue_id(self) -> VenueId:
    return VENUE

  @property
  def account_id(self) -> str:
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
    return ['mock', ALIAS]

  async def venue(self, id: str, /) -> TradingVenue:
    if id not in ('mock', ALIAS):
      raise ValueError(f'No account found for venue id: {id}')
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
    settings: Settings = {},
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
  assert await sdk.venues() == ['mock', ALIAS]
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


@pytest.mark.parametrize(
  'msg',
  [
    codec.DepthReq(id='d', market_id=MARKET_ID, levels=1),
    codec.DepthReq(
      id='d', market_id=MARKET_ID, settings={'hyperliquid': {'depth_source': 'bbo'}}
    ),
    codec.DepthStreamReq(id='s', market_id=MARKET_ID),
    codec.DepthStreamReq(
      id='s',
      market_id=MARKET_ID,
      levels=3,
      settings={'hyperliquid': {'depth_source': 'fast'}},
    ),
  ],
)
def test_depth_requests_roundtrip_settings(
  msg: codec.DepthReq | codec.DepthStreamReq,
) -> None:
  """Depth requests carry `settings` through the codec, empty by default."""
  assert codec.decode_client(codec.encode_client(msg)) == msg


@pytest.mark.parametrize('tag', ['depth', 'depth_stream'])
def test_depth_frames_without_settings_decode(tag: str) -> None:
  """Frames from clients that predate depth `settings` decode to empty settings."""
  frame = f'{{"tag": "{tag}", "id": "x", "market_id": "{MARKET_ID}"}}'
  msg = codec.decode_client(frame)
  assert isinstance(msg, codec.DepthReq | codec.DepthStreamReq)
  assert msg.settings == {}


@pytest.mark.parametrize(
  'msg',
  [
    codec.TradesStreamReq(id='t', market_id=MARKET_ID),
    codec.TradesStreamReq(
      id='t',
      market_id=MARKET_ID,
      queue_size=10,
      settings={'dydx': {'trades_source': 'fastest'}},
    ),
  ],
)
def test_trades_stream_request_roundtrips_settings(msg: codec.TradesStreamReq) -> None:
  """Trades stream requests carry `settings` through the codec, empty by default."""
  assert codec.decode_client(codec.encode_client(msg)) == msg


def test_trades_stream_frame_without_settings_decodes() -> None:
  """Frames from clients that predate trades `settings` decode to empty settings."""
  frame = f'{{"tag": "trades_stream", "id": "x", "market_id": "{MARKET_ID}"}}'
  msg = codec.decode_client(frame)
  assert isinstance(msg, codec.TradesStreamReq)
  assert msg.settings == {}


TIMED_TRADE = Trade(
  id='t1',
  price=Decimal('100'),
  qty=Decimal('1'),
  time=datetime(2026, 10, 9, tzinfo=timezone.utc),
  maker=True,
)
"""A fill with the venue's execution time."""
UNTIMED_TRADE = Trade(
  id='10:fill:0',
  price=Decimal('100'),
  qty=Decimal('-1'),
  time=None,
  maker=False,
  details={'source': 'node', 'height': 10},
)
"""A fill whose feed reports no execution time, like a dYdX full-node fill."""


@pytest.mark.parametrize(
  'msg',
  [
    codec.TradesDataMsg(id='t', trade=TIMED_TRADE),
    codec.TradesDataMsg(id='t', trade=UNTIMED_TRADE),
    codec.TradesHistoryResp(id='h', trades=[TIMED_TRADE, UNTIMED_TRADE]),
  ],
)
def test_trades_roundtrip_with_and_without_time(
  msg: codec.TradesDataMsg | codec.TradesHistoryResp,
) -> None:
  """Trades keep their `time`, including `None`, through the codec."""
  decoded = codec.decode_server(codec.encode_server(msg))
  if isinstance(msg, codec.TradesHistoryResp):
    assert isinstance(decoded, codec.TradesHistoryResp)
    assert list(decoded.trades) == list(msg.trades)
  else:
    assert decoded == msg


@pytest.mark.asyncio
async def test_untimed_trades_stream_through_gateway(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  """A trade without `time` reaches the proxy client with `time=None`."""
  mock_state.trades_stream_items = [UNTIMED_TRADE, TIMED_TRADE]
  market = await sdk.perp_market(MARKET_ID)

  async with market.trades_stream() as stream:
    got = [item async for item in stream]

  assert got == [UNTIMED_TRADE, TIMED_TRADE]


@pytest.mark.asyncio
async def test_trades_stream_settings_pass_through_gateway(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  """`trades_stream` settings reach the gateway-side market unchanged."""
  settings: Settings = {'dydx': {'trades_source': 'node'}}
  market = await sdk.perp_market(MARKET_ID)

  async with market.trades_stream() as stream:
    [item async for item in stream]
  async with market.trades_stream(settings=settings) as stream:
    [item async for item in stream]

  assert mock_state.trades_settings == [{}, settings]


@pytest.mark.asyncio
async def test_depth_settings_pass_through_gateway(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  """`depth`/`depth_stream` settings reach the gateway-side market unchanged."""
  settings: Settings = {'hyperliquid': {'depth_source': 'bbo'}}
  mock_state.depth_stream_items = [book('100')]
  market = await sdk.perp_market(MARKET_ID)

  await market.depth()
  await market.depth(settings=settings)
  async with market.depth_stream(settings=settings) as stream:
    [item async for item in stream]

  assert mock_state.depth_settings == [{}, settings, settings]


@pytest.mark.asyncio
async def test_depth_streams_with_different_settings_are_independent(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  """Two streams on one market with different settings are separate subscriptions."""
  mock_state.depth_stream_items = [book('100'), book('110')]
  mock_state.depth_stream_wait = True
  market = await sdk.perp_market(MARKET_ID)

  async with (
    market.depth_stream(queue_size=10, overflow='fail') as default,
    market.depth_stream(
      queue_size=10,
      overflow='fail',
      settings={'hyperliquid': {'depth_source': 'bbo'}},
    ) as bbo,
  ):
    default_items, bbo_items = aiter(default), aiter(bbo)
    default_prices = [(await anext(default_items)).best_bid.price for _ in range(2)]
    bbo_prices = [(await anext(bbo_items)).best_bid.price for _ in range(2)]
    assert len((await sdk._conn.ctx).subs) == 2

  assert default_prices == [Decimal('99'), Decimal('109')]
  assert bbo_prices == [Decimal('199'), Decimal('199')]
  assert (await sdk._conn.ctx).subs == {}


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


def test_order_rejected_codec_roundtrip() -> None:
  exc_cls = codec.decode_exception(codec.encode_exception(OrderRejected('no match')))

  assert exc_cls is OrderRejected
  assert issubclass(exc_cls, ApiError)


@pytest.mark.asyncio
async def test_order_rejected_survives_gateway(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  mock_state.place_order_error = OrderRejected('could not immediately match')
  market = await sdk.perp_market(MARKET_ID)
  order: Order = {'type': 'MARKET', 'qty': Decimal('1'), 'price': Decimal('100')}

  with pytest.raises(OrderRejected, match='could not immediately match'):
    await market.place_order(order)


@pytest.mark.asyncio
async def test_ambiguous_api_error_is_not_order_rejected_through_gateway(
  sdk: ProxySDK, mock_state: MockState
) -> None:
  mock_state.place_order_error = ApiError(502, 'Bad Gateway')
  market = await sdk.perp_market(MARKET_ID)
  order: Order = {'type': 'MARKET', 'qty': Decimal('1'), 'price': Decimal('100')}

  with pytest.raises(ApiError) as raised:
    await market.place_order(order)

  assert not isinstance(raised.value, OrderRejected)


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


@pytest.mark.asyncio
async def test_leverage_forwards_refetch_through_gateway(sdk: ProxySDK) -> None:
  """The gateway-side market owns the cache; `refetch` crosses the wire."""
  sent = record_calls(sdk)
  assert await sdk.leverage(MARKET_ID) == Decimal('5')
  assert await sdk.leverage(MARKET_ID, refetch=True) == Decimal('4')
  requests = [req for req in sent if isinstance(req, codec.LeverageReq)]
  assert [req.refetch for req in requests] == [False, True]
  assert all(req.market_id == MARKET_ID for req in requests)


@pytest.mark.parametrize(
  'msg',
  [
    codec.LeverageReq(id='l', market_id=MARKET_ID),
    codec.LeverageReq(id='l', market_id=MARKET_ID, refetch=True),
  ],
)
def test_leverage_request_roundtrips(msg: codec.LeverageReq) -> None:
  """The leverage request keeps its market and refetch flag on the wire."""
  assert codec.decode_client(codec.encode_client(msg)) == msg


def test_leverage_response_keeps_decimal_value() -> None:
  """Fractional leverage (dYdX's `1 / effective IMF`) survives as a `Decimal`."""
  msg = codec.LeverageResp(id='l', value=Decimal('1.818181818181818181818181818'))
  assert codec.decode_server(codec.encode_server(msg)) == msg


def record_calls(sdk: ProxySDK) -> list[codec.CallReq]:
  """Record every unary request the proxy sends, still forwarding it."""
  sent: list[codec.CallReq] = []
  call = sdk._conn.call

  async def recording(req: codec.CallReq) -> Any:
    """Record, then forward the request."""
    sent.append(req)
    return await call(req)

  sdk._conn.call = recording  # type: ignore[method-assign]
  return sent


@pytest.mark.asyncio
async def test_market_reports_venue_and_keeps_address(sdk: ProxySDK) -> None:
  """An aliased account reports the gateway's venue; requests keep the account address."""
  sent = record_calls(sdk)
  market = await sdk.perp_market(ALIAS_MARKET_ID)

  assert market.venue_id == VENUE
  assert market.account_id == ALIAS
  assert market.id == ALIAS_MARKET_ID
  assert (market.exchange_id, market.market_id) == ('perp', 'BTC-USD')
  assert (await market.depth()).best_bid.price == Decimal('99')
  assert [type(req) for req in sent] == [codec.ExchangeReq, codec.DepthReq]
  depth = sent[1]
  assert isinstance(depth, codec.DepthReq)
  assert depth.market_id == ALIAS_MARKET_ID


@pytest.mark.asyncio
async def test_resolutions_are_cached_per_address(sdk: ProxySDK) -> None:
  """Repeated market, exchange and venue resolutions do not round-trip again."""
  sent = record_calls(sdk)
  await sdk.perp_market(ALIAS_MARKET_ID)
  spot_view = await sdk.market(ALIAS_MARKET_ID)
  exchange = await sdk.perp_exchange(f'{ALIAS}:perp')
  venue = await sdk.venue(ALIAS)

  assert (exchange.id, exchange.account_id, exchange.venue_id) == (
    f'{ALIAS}:perp',
    ALIAS,
    VENUE,
  )
  assert (venue.id, venue.account_id, venue.venue_id) == (ALIAS, ALIAS, VENUE)
  assert (spot_view.id, spot_view.account_id, spot_view.venue_id) == (
    ALIAS_MARKET_ID,
    ALIAS,
    VENUE,
  )
  assert await sdk.venue(ALIAS) is venue
  assert await venue.exchange('perp') is exchange
  assert [type(req) for req in sent] == [codec.ExchangeReq, codec.VenueReq]


@pytest.mark.asyncio
async def test_unknown_account_fails_resolution_without_caching(sdk: ProxySDK) -> None:
  """Resolution errors surface as before and leave nothing cached."""
  for _ in range(2):
    with pytest.raises(ValueError, match='No account found for venue id: nope'):
      await sdk.market('nope:perp:BTC-USD')
    with pytest.raises(ValueError, match='No account found for venue id: nope'):
      await sdk.venue('nope')
  assert sdk._exchanges == {}
  assert sdk._venues == {}


@pytest.mark.parametrize(
  'msg',
  [
    codec.ExchangeResp(id='e', type='perp', venue_id='hyperliquid'),
    codec.ExchangeResp(id='e', type='spot', venue_id='dydx_testnet'),
    codec.VenueResp(id='v', venue_id='hyperliquid'),
  ],
)
def test_resolution_replies_roundtrip(
  msg: codec.ExchangeResp | codec.VenueResp,
) -> None:
  """Resolution replies carry the venue through the codec."""
  assert codec.decode_server(codec.encode_server(msg)) == msg


@pytest.mark.parametrize(
  'raw',
  [
    '{"tag": "exchange", "id": "e", "type": "perp"}',
    '{"tag": "exchange", "id": "e", "type": "perp", "venue_id": "hl"}',
    '{"tag": "venue", "id": "v", "venue_id": "mock"}',
  ],
)
def test_resolution_replies_require_a_known_venue(raw: str) -> None:
  """A reply without a venue, or naming an account key instead, is rejected."""
  with pytest.raises(pydantic.ValidationError):
    codec.decode_server(raw)


@pytest.mark.parametrize(
  'msg',
  [
    codec.VenueReq(id='r', account_id=ALIAS),
    codec.ExchangeReq(id='r', account_id=ALIAS, exchange_id='perp'),
    codec.ExchangesReq(id='r', account_id=ALIAS),
    codec.MarketsReq(id='r', account_id=ALIAS, exchange_id='perp'),
    codec.TickersReq(id='r', account_id=ALIAS, exchange_id='perp'),
    codec.PerpStatsReq(id='r', account_id=ALIAS, exchange_id='perp'),
    codec.ExchangeCollateralReq(id='r', account_id=ALIAS, exchange_id='perp'),
    codec.ExchangePerpCollateralReq(id='r', account_id=ALIAS, exchange_id='perp'),
  ],
)
def test_account_requests_roundtrip(msg: codec.CallReq) -> None:
  """Venue and exchange requests address the venue by `account_id` on the wire."""
  assert codec.decode_client(codec.encode_client(msg)) == msg
  wire = json.loads(codec.encode_client(msg))
  assert wire['account_id'] == ALIAS
  assert 'venue_id' not in wire


@dataclass
class LegacyTradesMarket(MockMarket):
  """A venue market from before `trades_stream` took `settings`."""

  @asynccontextmanager
  async def trades_stream(  # type: ignore[override]
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    async def gen() -> AsyncIterator[Trade]:
      yield Trade(
        id='t1',
        price=Decimal('100'),
        qty=Decimal('1'),
        time=datetime(2026, 10, 9, tzinfo=timezone.utc),
        maker=True,
      )

    yield gen()


class LegacyTradesGateway(Gateway):
  def __init__(self, sdk: TradingMarkets, market: LegacyTradesMarket):
    super().__init__(sdk)
    self.market = market

  async def _market(self, market_id: str) -> PerpMarket:
    assert market_id == MARKET_ID
    return self.market


@pytest.mark.asyncio
async def test_gateway_trades_stream_serves_a_market_without_settings() -> None:
  """Without settings the gateway leaves the argument out, so a venue released before
  `trades_stream` took `settings` keeps streaming; asking for settings fails it."""
  gateway = LegacyTradesGateway(
    MockSDK(MockState()),  # type: ignore[arg-type]
    market=LegacyTradesMarket(MockState()),
  )
  results: list[list[codec.ServerMsg]] = []
  for req in [
    codec.TradesStreamReq(id='plain', market_id=MARKET_ID),
    codec.TradesStreamReq(
      id='dydx', market_id=MARKET_ID, settings={'dydx': {'trades_source': 'node'}}
    ),
  ]:
    ws = FakeWebSocket()
    sub_tasks: dict[str, asyncio.Task[None]] = {}
    task = asyncio.create_task(gateway._stream(ws, req, sub_tasks))  # type: ignore
    sub_tasks[req.id] = task
    await asyncio.wait_for(task, timeout=1)
    results.append(ws.sent)

  plain, dydx = results
  assert [type(m) for m in plain] == [codec.TradesDataMsg, codec.EndMsg]
  assert isinstance(plain[-1], codec.EndMsg) and plain[-1].exc is None
  end = dydx[-1]
  assert isinstance(end, codec.EndMsg) and end.exc is not None
