"""Gateway WebSocket proxy: Connection, ProxySDK/Market/Exchange/Venue."""

from typing_extensions import Any, AsyncIterable, Sequence, Collection, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
import asyncio
import logging
from uuid import uuid4
from types import TracebackType

import aiohttp

from tribulnation.sdk.core import (
  PaginatedResponse,
  StreamInbox,
  OverflowPolicy,
)
from tribulnation.sdk.market import TradingMarkets, Market, PerpMarket
from tribulnation.sdk.market.venue import TradingVenue, ExchangeDescription
from tribulnation.sdk.market.exchange import Exchange, PerpExchange
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  NextFunding,
  Ticker,
  PerpStats,
  Trade,
  Rules,
  Settings,
  Order,
  OrderResponse,
  OrderState,
  Position,
  PerpPosition,
  Collateral,
  PerpCollateral,
  FundingRate,
  FundingPayment,
)

from . import codec

log = logging.getLogger(__name__)


class GatewayError(Exception):
  """Report a gateway connection failure."""

  def __init__(self, message: str, exc_type: str | None = None):
    """Initialize the gateway error."""
    super().__init__(message)
    self.exc_type = exc_type


@dataclass
class Connection:
  """Multiplexed WebSocket connection to the SDK gateway."""

  @dataclass(kw_only=True)
  class Context:
    """Hold the active transport and its pending consumers."""

    ws: aiohttp.ClientWebSocketResponse
    session: aiohttp.ClientSession
    recv_task: asyncio.Task[None]
    pending: dict[str, asyncio.Future[Any]] = field(
      default_factory=dict[str, asyncio.Future[Any]]
    )
    subs: dict[str, StreamInbox[Any]] = field(
      default_factory=dict[str, StreamInbox[Any]]
    )

  url: str
  _ctx: Context | None = None
  lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

  @property
  async def ctx(self):
    """Get or open the shared connection context."""
    async with self.lock:
      if self._ctx is None:
        self._ctx = await self.connect()
    return self._ctx

  async def connect(self):
    """Connect to the gateway.

    Accepts a ``ws://`` / ``wss://`` TCP URL or a ``unix://path`` Unix-socket
    path.  For Unix sockets, ``aiohttp.UnixConnector`` is used and the HTTP
    upgrade request targets the dummy host ``localhost``.
    """
    if self.url.startswith('unix://'):
      path = self.url[len('unix://') :]
      connector = aiohttp.UnixConnector(path=path)
      session = aiohttp.ClientSession(connector=connector)
      try:
        ws = await session.ws_connect('http://localhost/')
      except Exception:
        await session.close()
        raise
    else:
      session = aiohttp.ClientSession()
      try:
        ws = await session.ws_connect(self.url)
      except Exception:
        await session.close()
        raise

    self._ctx = self.Context(
      ws=ws, session=session, recv_task=asyncio.create_task(self._recv_loop())
    )
    return self._ctx

  async def close(self) -> None:
    """Close the active connection and its receive task."""
    if (ctx := self._ctx) is not None and not self.lock.locked():
      async with self.lock:
        ctx.recv_task.cancel()
        await ctx.ws.close()
        await ctx.session.close()
        if self._ctx is ctx:
          self._ctx = None

  async def __aenter__(self):
    """Open the gateway connection."""
    await self.connect()
    return self

  async def __aexit__(
    self,
    exc_type: type[BaseException] | None,
    exc_val: BaseException | None,
    exc_tb: TracebackType | None,
  ):
    """Close the gateway connection."""
    await self.close()

  async def call(self, req: codec.CallReq) -> Any:
    """Send one request and await its correlated response."""
    ctx = await self.ctx
    fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    ctx.pending[req.id] = fut
    await ctx.ws.send_bytes(codec.encode_client(req))
    return await fut

  async def subscribe(
    self,
    req: codec.StreamReq,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> tuple[StreamInbox[Any], str]:
    """Open a bounded inbox for a remote stream."""
    ctx = await self.ctx
    inbox = StreamInbox[Any].new(queue_size=queue_size, overflow=overflow)
    ctx.subs[req.id] = inbox
    await ctx.ws.send_bytes(codec.encode_client(req))
    return inbox, req.id

  async def unsubscribe(self, mid: str) -> None:
    """Cancel a remote stream and remove its local inbox."""
    ctx = await self.ctx
    # Send before removing so the server frame doesn't arrive after we've
    # already dropped the queue reference.
    await ctx.ws.send_bytes(codec.encode_client(codec.UnsubMsg(id=mid)))
    ctx.subs.pop(mid, None)

  async def _recv_loop(self) -> None:
    """Dispatch incoming replies and stream messages to their consumers."""
    ctx = await self.ctx
    try:
      async for msg in ctx.ws:
        if msg.type != aiohttp.WSMsgType.BINARY:
          continue
        m = codec.decode_server(msg.data)
        match m:
          case codec.ErrMsg():
            fut = ctx.pending.pop(m.id, None)
            if fut and not fut.done():
              exc_cls = codec.decode_exception(m.exc or '')
              fut.set_exception(exc_cls(m.error))
          case codec.EndMsg():
            inbox = ctx.subs.pop(m.id, None)
            if inbox:
              if m.error:
                exc_cls = codec.decode_exception(m.exc or '')
                inbox.fail(exc_cls(m.error))
              else:
                inbox.close()
          case codec.DepthDataMsg() | codec.TradesDataMsg():
            inbox = ctx.subs.get(m.id)
            if inbox and not inbox.push(m):
              ctx.subs.pop(m.id, None)
          case _:
            fut = ctx.pending.pop(m.id, None)
            if fut and not fut.done():
              fut.set_result(m)
    finally:
      # Connection dropped (however the loop ended: clean close, error, or
      # cancellation): drop the cached context so the next `.ctx` access
      # reconnects instead of reusing a dead socket forever.
      if self._ctx is ctx:
        self._ctx = None
      # Unblock all callers so they don't hang forever.
      err = GatewayError('WebSocket connection closed')
      for fut in ctx.pending.values():
        if not fut.done():
          fut.set_exception(err)
      ctx.pending.clear()
      for inbox in ctx.subs.values():
        inbox.fail(err)
      ctx.subs.clear()
      try:
        await ctx.ws.close()
      except Exception:
        log.exception('websocket close failed during connection cleanup')
      try:
        await ctx.session.close()
      except Exception:
        log.exception('session close failed during connection cleanup')


@dataclass
class ProxyMarket(Market):
  """A spot market forwarding calls to the gateway over WebSocket."""

  _conn: Connection
  _venue_id: str
  _exchange_id: str
  _market_id: str

  @classmethod
  def of(cls, conn: Connection, full_id: str):
    """Return the of."""
    venue_id, exchange_id, market_id = full_id.split(':', 2)
    return cls(conn, venue_id, exchange_id, market_id)

  @property
  def venue_id(self) -> str:
    """Return the venue id."""
    return self._venue_id

  @property
  def exchange_id(self) -> str:
    """Return the exchange id."""
    return self._exchange_id

  @property
  def market_id(self) -> str:
    """Return the market id."""
    return self._market_id

  def _mid(self) -> str:
    """Allocate a request correlation ID."""
    return str(uuid4())

  # ── Market ────────────────────────────────────────────────────────────

  async def depth(self, *, levels: int | None = None) -> Book:
    """Forward depth through the gateway."""
    resp: codec.DepthResp = await self._conn.call(
      codec.DepthReq(id=self._mid(), market_id=self.id, levels=levels)
    )
    return resp.book

  @asynccontextmanager
  async def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ):
    """Forward depth stream through the gateway."""
    inbox, sub_id = await self._conn.subscribe(
      codec.DepthStreamReq(
        id=self._mid(),
        market_id=self.id,
        levels=levels,
        queue_size=queue_size,
        overflow=overflow,
      ),
      queue_size=queue_size,
      overflow=overflow,
    )
    try:

      async def gen() -> AsyncIterable[Book]:
        """Yield remote results to the SDK consumer."""
        async for item in inbox:
          if not isinstance(item, codec.DepthDataMsg):
            raise RuntimeError(f'Unexpected depth stream item type {type(item)}')
          yield item.book

      yield gen()
    finally:
      await self._conn.unsubscribe(sub_id)

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Forward rules through the gateway."""
    resp: codec.RulesResp = await self._conn.call(
      codec.RulesReq(id=self._mid(), market_id=self.id, refetch=refetch)
    )
    return resp.rules

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Fetch account rates without falling back to public rules."""
    resp: codec.FeesResp = await self._conn.call(
      codec.FeesReq(id=self._mid(), market_id=self.id, refetch=refetch)
    )
    return resp.fees

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Fetch historical candles; the venue validates interval support."""

    async def gen():
      """Expose the gateway response as an SDK page."""
      resp: codec.CandlesResp = await self._conn.call(
        codec.CandlesReq(
          id=self._mid(), market_id=self.id, interval=interval, start=start, end=end
        )
      )
      yield resp.candles

    return PaginatedResponse(gen())

  async def collateral(self) -> Collateral:
    """Fetch this market's actual collateral bucket."""
    resp: codec.CollateralResp = await self._conn.call(
      codec.CollateralReq(id=self._mid(), market_id=self.id)
    )
    return resp.collateral

  async def open_orders(self) -> Sequence[OrderState]:
    """Forward open orders through the gateway."""
    resp: codec.OpenOrdersResp = await self._conn.call(
      codec.OpenOrdersReq(id=self._mid(), market_id=self.id)
    )
    return resp.orders

  async def query_order(self, id: str) -> OrderState | None:
    """Forward query order through the gateway."""
    resp: codec.QueryOrderResp = await self._conn.call(
      codec.QueryOrderReq(id=self._mid(), market_id=self.id, order_id=id)
    )
    return resp.order

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Forward trades history through the gateway."""

    async def gen():
      """Yield remote results to the SDK consumer."""
      resp: codec.TradesHistoryResp = await self._conn.call(
        codec.TradesHistoryReq(id=self._mid(), market_id=self.id, start=start, end=end)
      )
      yield resp.trades

    return PaginatedResponse(gen())

  @asynccontextmanager
  async def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ):
    """Forward trades stream through the gateway."""
    inbox, sub_id = await self._conn.subscribe(
      codec.TradesStreamReq(
        id=self._mid(),
        market_id=self.id,
        queue_size=queue_size,
        overflow=overflow,
      ),
      queue_size=queue_size,
      overflow=overflow,
    )
    try:

      async def gen() -> AsyncIterable[Trade]:
        """Yield remote results to the SDK consumer."""
        async for item in inbox:
          if not isinstance(item, codec.TradesDataMsg):
            raise RuntimeError(f'Unexpected trades stream item type {type(item)}')
          yield item.trade

      yield gen()
    finally:
      await self._conn.unsubscribe(sub_id)

  async def position(self) -> Position:
    """Forward position through the gateway."""
    resp: codec.PositionResp = await self._conn.call(
      codec.PositionReq(id=self._mid(), market_id=self.id)
    )
    return resp.position

  async def available_notional(self) -> Decimal:
    """Forward available notional through the gateway."""
    resp: codec.AvailableNotionalResp = await self._conn.call(
      codec.AvailableNotionalReq(id=self._mid(), market_id=self.id)
    )
    return resp.value

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Forward place order through the gateway."""
    resp: codec.PlaceOrderResp = await self._conn.call(
      codec.PlaceOrderReq(
        id=self._mid(), market_id=self.id, order=order, settings=settings
      )
    )
    return resp.response

  async def place_orders(
    self, orders: Sequence[Order], *, settings: Settings = {}
  ) -> Sequence[OrderResponse]:
    """Forward place orders through the gateway."""
    return list(
      await asyncio.gather(*[self.place_order(o, settings=settings) for o in orders])
    )

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Forward cancel order through the gateway."""
    resp: codec.CancelOrderResp = await self._conn.call(
      codec.CancelOrderReq(
        id=self._mid(), market_id=self.id, order_id=id, settings=settings
      )
    )
    return resp.result

  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Forward cancel orders through the gateway."""
    return await asyncio.gather(
      *[self.cancel_order(id, settings=settings) for id in ids]
    )

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Forward cancel open orders through the gateway."""
    resp: codec.CancelOpenOrdersResp = await self._conn.call(
      codec.CancelOpenOrdersReq(id=self._mid(), market_id=self.id, settings=settings)
    )
    return resp.result


@dataclass
class ProxyPerpMarket(ProxyMarket, PerpMarket):
  """A perpetual market with funding, position and margin RPCs."""

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Forward index through the gateway."""
    resp: codec.IndexResp = await self._conn.call(
      codec.IndexReq(id=self._mid(), market_id=self.id, settings=settings)
    )
    return resp.value

  async def next_funding(self) -> NextFunding:
    """Forward next funding through the gateway."""
    resp: codec.NextFundingResp = await self._conn.call(
      codec.NextFundingReq(id=self._mid(), market_id=self.id)
    )
    return resp.rate

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Forward funding rates through the gateway."""

    async def gen():
      """Yield remote results to the SDK consumer."""
      resp: codec.FundingRatesResp = await self._conn.call(
        codec.FundingRatesReq(id=self._mid(), market_id=self.id, start=start, end=end)
      )
      yield resp.rates

    return PaginatedResponse(gen())

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Forward funding payments through the gateway."""

    async def gen():
      """Yield remote results to the SDK consumer."""
      resp: codec.FundingPaymentsResp = await self._conn.call(
        codec.FundingPaymentsReq(
          id=self._mid(), market_id=self.id, start=start, end=end
        )
      )
      yield resp.payments

    return PaginatedResponse(gen())

  async def perp_position(self) -> PerpPosition:
    """Forward perp position through the gateway."""
    resp: codec.PerpPositionResp = await self._conn.call(
      codec.PerpPositionReq(id=self._mid(), market_id=self.id)
    )
    return resp.position

  async def collateral(self) -> Collateral:
    """Forward collateral through the gateway."""
    return await self.perp_collateral()

  async def perp_collateral(self) -> PerpCollateral:
    """Forward perp collateral through the gateway."""
    resp: codec.PerpCollateralResp = await self._conn.call(
      codec.PerpCollateralReq(id=self._mid(), market_id=self.id)
    )
    return resp.collateral


@dataclass
class ProxyExchange(Exchange):
  """A spot exchange constructing markets and forwarding bulk calls."""

  _conn: Connection
  _venue_id: str
  _exchange_id: str

  @property
  def venue_id(self) -> str:
    """Return the venue id."""
    return self._venue_id

  @property
  def exchange_id(self) -> str:
    """Return the exchange id."""
    return self._exchange_id

  async def market(self, market_id: str, /) -> Market:
    """Forward market through the gateway."""
    return ProxyMarket(self._conn, self._venue_id, self._exchange_id, market_id)

  async def markets(self) -> Sequence[str]:
    """Forward markets through the gateway."""
    resp: codec.MarketsResp = await self._conn.call(
      codec.MarketsReq(
        id=str(uuid4()), venue_id=self._venue_id, exchange_id=self._exchange_id
      )
    )
    return resp.markets

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Fetch native bulk tickers, including both volume fields."""
    resp: codec.TickersResp = await self._conn.call(
      codec.TickersReq(
        id=str(uuid4()),
        venue_id=self._venue_id,
        exchange_id=self._exchange_id,
        markets=list(markets) if markets is not None else None,
        settings=settings,
      )
    )
    return resp.tickers

  async def collateral(self, market_id: str | None = None, /) -> Collateral:
    """Fetch market collateral or the exchange's own bucket."""
    if market_id is not None:
      return await (await self.market(market_id)).collateral()
    resp: codec.CollateralResp = await self._conn.call(
      codec.ExchangeCollateralReq(
        id=str(uuid4()), venue_id=self._venue_id, exchange_id=self._exchange_id
      )
    )
    return resp.collateral


@dataclass
class ProxyPerpExchange(ProxyExchange, PerpExchange):
  """A perpetual exchange constructing perpetual market proxies."""

  async def market(self, market_id: str, /) -> PerpMarket:
    """Borrow a perpetual market on this connection."""
    return ProxyPerpMarket(self._conn, self._venue_id, self._exchange_id, market_id)

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Fetch native bulk funding and pricing statistics."""
    resp: codec.PerpStatsResp = await self._conn.call(
      codec.PerpStatsReq(
        id=str(uuid4()),
        venue_id=self._venue_id,
        exchange_id=self._exchange_id,
        markets=list(markets) if markets is not None else None,
        settings=settings,
      )
    )
    return resp.stats

  async def collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """Preserve perpetual margin fields for generic collateral callers."""
    return await self.perp_collateral(market_id)

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """Forward perp collateral through the gateway."""
    if market_id is not None:
      market = await self.market(market_id)
      return await market.perp_collateral()
    resp: codec.PerpCollateralResp = await self._conn.call(
      codec.ExchangePerpCollateralReq(
        id=str(uuid4()), venue_id=self._venue_id, exchange_id=self._exchange_id
      )
    )
    return resp.collateral


@dataclass
class ProxyVenue(TradingVenue):
  """A TradingVenue that constructs ProxyExchanges and forwards list calls."""

  _conn: Connection
  _venue_id: str

  @property
  def venue_id(self) -> str:
    """Return the venue id."""
    return self._venue_id

  async def exchange(self, exchange_id: str, /) -> Exchange:
    """Resolve product type at the gateway instead of guessing from the ID."""
    resp: codec.ExchangeResp = await self._conn.call(
      codec.ExchangeReq(
        id=str(uuid4()), venue_id=self._venue_id, exchange_id=exchange_id
      )
    )
    cls = ProxyPerpExchange if resp.type == 'perp' else ProxyExchange
    return cls(self._conn, self._venue_id, exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Require a perpetual product before exposing perpetual operations."""
    exchange = await self.exchange(exchange_id)
    if not isinstance(exchange, PerpExchange):
      raise ValueError(f'Exchange {exchange.id} is not perpetual')
    return exchange

  async def exchanges(self) -> Sequence[ExchangeDescription]:
    """Forward exchanges through the gateway."""
    resp: codec.ExchangesResp = await self._conn.call(
      codec.ExchangesReq(id=str(uuid4()), venue_id=self._venue_id)
    )
    return resp.exchanges


@dataclass
class ProxySDK(TradingMarkets):
  """TradingMarkets backed by the SDK gateway WebSocket."""

  _conn: Connection

  @classmethod
  def at(cls, url: str = 'unix:///tmp/engine-gateway.sock') -> 'ProxySDK':
    """Construct a remote SDK at a Unix socket or WebSocket URL."""
    return cls(Connection(url))

  def resources(self):
    """Own the gateway connection through the SDK lifecycle."""
    yield self._conn

  async def venues(self) -> Sequence[str]:
    """Forward venues through the gateway."""
    resp: codec.VenuesResp = await self._conn.call(codec.VenuesReq(id=str(uuid4())))
    return resp.venues

  async def venue(self, id: str, /) -> TradingVenue:
    """Forward venue through the gateway."""
    return ProxyVenue(self._conn, id)
