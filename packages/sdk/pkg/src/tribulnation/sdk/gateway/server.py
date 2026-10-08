"""SDK WebSocket gateway: owns venue connections and fans out streams to clients."""

from dataclasses import dataclass, field
from collections import defaultdict
import asyncio
import logging
import os
import signal

import aiohttp
from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError

from tribulnation.sdk.gateway.diagnostics import memory_snapshot
from tribulnation.sdk import TradingMarkets, Market, PerpMarket
from tribulnation.sdk.market import Book, Trade, PerpExchange

from . import codec

log = logging.getLogger(__name__)


@dataclass
class Gateway:
  """Handles WebSocket connections; owns venue connections and stream subscriptions."""

  _sdk: TradingMarkets
  _markets: dict[str, Market] = field(default_factory=dict[str, Market])
  _market_locks: defaultdict[str, asyncio.Lock] = field(
    default_factory=lambda: defaultdict(asyncio.Lock)
  )

  async def _market(self, market_id: str) -> Market:
    """Resolve and cache a market for this gateway."""
    if market_id not in self._markets:
      async with self._market_locks[market_id]:
        if market_id not in self._markets:
          self._markets[market_id] = await self._sdk.market(market_id)
    return self._markets[market_id]

  async def _perp_market(self, market_id: str) -> PerpMarket:
    """Require a perpetual market for this request."""
    mkt = await self._market(market_id)
    if not isinstance(mkt, PerpMarket):
      raise ValueError(f'market {market_id} is not a perpetual market')
    return mkt

  async def handler(self, request: web.Request) -> web.WebSocketResponse:
    """Serve multiplexed requests and streams on one WebSocket."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    peer = request.remote
    log.debug('connect %s', peer)

    sub_tasks: dict[str, asyncio.Task[None]] = {}
    call_tasks: set[asyncio.Task[None]] = set()

    try:
      async for msg in ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
          try:
            m = codec.decode_client(msg.data)
            match m:
              case codec.UnsubMsg():
                log.debug('← unsub [%s]', m.id[:8])
                task = sub_tasks.get(m.id)
                if task and not task.cancelling():
                  task.cancel()
              case codec.DepthStreamReq() | codec.TradesStreamReq():
                log.debug('← sub   [%s]', m.id[:8])
                sub_tasks[m.id] = asyncio.create_task(self._stream(ws, m, sub_tasks))
              case _:
                log.debug('← call  [%s] %s', m.id[:8], m.tag)
                task = asyncio.create_task(self._call(ws, m))
                call_tasks.add(task)
                task.add_done_callback(call_tasks.discard)
          except Exception as e:
            log.warning('malformed message: %s', e)
        elif msg.type == aiohttp.WSMsgType.ERROR:
          break
    finally:
      tasks = [*sub_tasks.values(), *call_tasks]
      for task in tasks:
        if not task.cancelling():
          task.cancel()
      if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
      log.debug('disconnect %s', peer)

    return ws

  async def debug_memory(self, request: web.Request) -> web.Response:
    """Report memory and cached market diagnostics."""
    return web.json_response(
      memory_snapshot(
        extra={
          'gateway': {
            'markets': len(self._markets),
            'market_ids': sorted(self._markets),
          }
        },
      )
    )

  async def _stream(
    self,
    ws: web.WebSocketResponse,
    msg: codec.StreamReq,
    sub_tasks: dict[str, asyncio.Task[None]],
  ):
    """Forward a venue subscription and close it on disconnect."""

    async def send_end(exc: Exception | None = None) -> bool:
      """Send stream completion if the transport is still writable."""
      if ws.closed:
        return False
      try:
        if exc is None:
          log.debug('→ end   [%s]', msg.id[:8])
          await _send(ws, codec.EndMsg(id=msg.id))
        else:
          error = _error_message(exc)
          log.debug('→ end   [%s] %s', msg.id[:8], error)
          await _send(
            ws,
            codec.EndMsg(id=msg.id, error=error, exc=codec.encode_exception(exc)),
          )
        return True
      except ClientConnectionResetError:
        log.debug('stream end skipped on closing transport [%s]', msg.id[:8])
        return False
      except (BrokenPipeError, ConnectionResetError):
        log.debug('stream end skipped on closed connection [%s]', msg.id[:8])
        return False
      except Exception:
        log.exception('stream end send failed [%s]', msg.id[:8])
        return False

    try:
      match msg:
        case codec.DepthStreamReq():
          market = await self._market(msg.market_id)
          # `depth_stream`/`trades_stream` return an `AsyncContextManager`:
          # calling them just constructs it, synchronously -- the actual
          # subscribe only happens on `__aenter__` below, so a subscribe
          # failure surfaces from the `async with`, not here. This `try`
          # still matters for `self._market(...)` itself, though.
          stream_cm = market.depth_stream(
            levels=msg.levels,
            queue_size=msg.queue_size,
            overflow=msg.overflow,
            settings=msg.settings,
          )
        case codec.TradesStreamReq():
          market = await self._market(msg.market_id)
          stream_cm = market.trades_stream(
            queue_size=msg.queue_size, overflow=msg.overflow
          )
    except Exception as e:
      await send_end(e)
      sub_tasks.pop(msg.id, None)
      return

    end_sent = False
    cancelled = False
    try:
      stream_error: Exception | None = None
      async with stream_cm as stream:
        try:
          async for item in stream:
            if ws.closed:
              break
            log.debug('→ data  [%s]', msg.id[:8])
            if isinstance(item, Book):
              await _send(ws, codec.DepthDataMsg(id=msg.id, book=item))
            elif isinstance(item, Trade):
              await _send(ws, codec.TradesDataMsg(id=msg.id, trade=item))
            else:
              raise RuntimeError(f'Unexpected stream item type {type(item)}')
        except asyncio.CancelledError:
          # Stop the consumer, then exit its subscription normally. Throwing
          # cancellation through a venue's decorated async generator can defer
          # its inner unsubscribe until after the owned socket has closed.
          cancelled = True
        except Exception as error:
          stream_error = error
      if stream_error is not None:
        raise stream_error
    except asyncio.CancelledError:
      cancelled = True
    except Exception as e:
      log.exception('stream failed [%s]', msg.id[:8])
      end_sent = await send_end(e)
    finally:
      sub_tasks.pop(msg.id, None)
      if not cancelled and not ws.closed and not end_sent:
        await send_end()

  async def _call(self, ws: web.WebSocketResponse, msg: codec.CallReq):
    """Dispatch a request and encode its response or error."""
    try:
      resp = await self._dispatch(msg)
      log.debug('→ ok    [%s]', msg.id[:8])
      await _send(ws, resp)
    except Exception as e:
      log.debug('→ err   [%s] %s', msg.id[:8], e)
      await _send(
        ws,
        codec.ErrMsg(id=msg.id, error=_error_message(e), exc=codec.encode_exception(e)),
      )

  async def _dispatch(self, msg: codec.CallReq) -> codec.ServerMsg:
    """Route a wire request to the owned SDK."""
    match msg:
      case codec.DepthReq():
        return codec.DepthResp(
          id=msg.id,
          book=await (await self._market(msg.market_id)).depth(
            levels=msg.levels, settings=msg.settings
          ),
        )
      case codec.FeesReq():
        return codec.FeesResp(
          id=msg.id,
          fees=await (await self._market(msg.market_id)).fees(refetch=msg.refetch),
        )
      case codec.CandlesReq():
        return codec.CandlesResp(
          id=msg.id,
          candles=await (await self._market(msg.market_id)).candles(
            msg.interval, msg.start, msg.end
          ),
        )
      case codec.ExchangeReq():
        exchange = await (await self._sdk.venue(msg.account_id)).exchange(
          msg.exchange_id
        )
        return codec.ExchangeResp(
          id=msg.id,
          type='perp' if isinstance(exchange, PerpExchange) else 'spot',
          venue_id=exchange.venue_id,
        )
      case codec.TickersReq():
        exchange = await (await self._sdk.venue(msg.account_id)).exchange(
          msg.exchange_id
        )
        return codec.TickersResp(
          id=msg.id,
          tickers=dict(await exchange.tickers(msg.markets, settings=msg.settings)),
        )
      case codec.PerpStatsReq():
        perp_exchange = await (await self._sdk.venue(msg.account_id)).perp_exchange(
          msg.exchange_id
        )
        return codec.PerpStatsResp(
          id=msg.id,
          stats=dict(
            await perp_exchange.perp_stats(msg.markets, settings=msg.settings)
          ),
        )
      case codec.ExchangeCollateralReq():
        exchange = await (await self._sdk.venue(msg.account_id)).exchange(
          msg.exchange_id
        )
        return codec.CollateralResp(id=msg.id, collateral=await exchange.collateral())
      case codec.RulesReq():
        return codec.RulesResp(
          id=msg.id,
          rules=await (await self._market(msg.market_id)).rules(refetch=msg.refetch),
        )
      case codec.OpenOrdersReq():
        return codec.OpenOrdersResp(
          id=msg.id,
          orders=list(await (await self._market(msg.market_id)).open_orders()),
        )
      case codec.QueryOrderReq():
        return codec.QueryOrderResp(
          id=msg.id,
          order=await (await self._market(msg.market_id)).query_order(msg.order_id),
        )
      case codec.TradesHistoryReq():
        return codec.TradesHistoryResp(
          id=msg.id,
          trades=await (await self._market(msg.market_id)).trades_history(
            msg.start, msg.end
          ),
        )
      case codec.PositionReq():
        return codec.PositionResp(
          id=msg.id, position=await (await self._market(msg.market_id)).position()
        )
      case codec.AvailableNotionalReq():
        return codec.AvailableNotionalResp(
          id=msg.id,
          value=await (await self._market(msg.market_id)).available_notional(),
        )
      case codec.PlaceOrderReq():
        return codec.PlaceOrderResp(
          id=msg.id,
          response=await (await self._market(msg.market_id)).place_order(
            msg.order, settings=msg.settings
          ),
        )
      case codec.CancelOrderReq():
        return codec.CancelOrderResp(
          id=msg.id,
          result=await (await self._market(msg.market_id)).cancel_order(
            msg.order_id, settings=msg.settings
          ),
        )
      case codec.CancelOpenOrdersReq():
        return codec.CancelOpenOrdersResp(
          id=msg.id,
          result=await (await self._market(msg.market_id)).cancel_open_orders(
            settings=msg.settings
          ),
        )
      case codec.IndexReq():
        return codec.IndexResp(
          id=msg.id,
          value=await (await self._perp_market(msg.market_id)).index(
            settings=msg.settings
          ),
        )
      case codec.NextFundingReq():
        return codec.NextFundingResp(
          id=msg.id,
          rate=await (await self._perp_market(msg.market_id)).next_funding(),
        )
      case codec.FundingRatesReq():
        return codec.FundingRatesResp(
          id=msg.id,
          rates=await (await self._perp_market(msg.market_id)).funding_rates(
            msg.start, msg.end
          ),
        )
      case codec.FundingPaymentsReq():
        return codec.FundingPaymentsResp(
          id=msg.id,
          payments=await (await self._perp_market(msg.market_id)).funding_payments(
            msg.start, msg.end
          ),
        )
      case codec.PerpPositionReq():
        return codec.PerpPositionResp(
          id=msg.id,
          position=await (await self._perp_market(msg.market_id)).perp_position(),
        )
      case codec.CollateralReq():
        return codec.CollateralResp(
          id=msg.id,
          collateral=await (await self._market(msg.market_id)).collateral(),
        )
      case codec.PerpCollateralReq():
        return codec.PerpCollateralResp(
          id=msg.id,
          collateral=await (await self._perp_market(msg.market_id)).perp_collateral(),
        )
      case codec.ExchangePerpCollateralReq():
        venue = await self._sdk.venue(msg.account_id)
        exchange = await venue.perp_exchange(msg.exchange_id)
        return codec.PerpCollateralResp(
          id=msg.id,
          collateral=await exchange.perp_collateral(),
        )
      case codec.MarketsReq():
        exc = await (await self._sdk.venue(msg.account_id)).exchange(msg.exchange_id)
        return codec.MarketsResp(id=msg.id, markets=list(await exc.markets()))
      case codec.ExchangesReq():
        return codec.ExchangesResp(
          id=msg.id,
          exchanges=list(await (await self._sdk.venue(msg.account_id)).exchanges()),
        )
      case codec.VenueReq():
        venue = await self._sdk.venue(msg.account_id)
        return codec.VenueResp(id=msg.id, venue_id=venue.venue_id)
      case codec.VenuesReq():
        return codec.VenuesResp(id=msg.id, venues=list(await self._sdk.venues()))


async def _send(ws: web.WebSocketResponse, msg: codec.ServerMsg):
  """Write a response on an open WebSocket."""
  if not ws.closed:
    await ws.send_bytes(codec.encode_server(msg))


def _error_message(exc: Exception) -> str:
  """Extract a printable remote error message."""
  if exc.args:
    return ', '.join(str(arg) for arg in exc.args if arg is not None)
  return str(exc)


def gateway_app(sdk: TradingMarkets) -> web.Application:
  """Own venue resources for exactly the lifetime of the gateway application."""
  gateway = Gateway(sdk)

  async def sdk_lifetime(app: web.Application):
    """Enter before serving and exit after request and stream cleanup."""
    async with sdk:
      yield

  app = web.Application()
  app.cleanup_ctx.append(sdk_lifetime)
  app.router.add_get('/', gateway.handler)
  app.router.add_get('/debug/memory', gateway.debug_memory)
  return app


async def run_gateway(socket_path: str, sdk: TradingMarkets):
  """Run Gateway as a standalone process on a Unix socket.

  Blocks until SIGTERM or SIGINT, then cleans up the socket file.
  """
  app = gateway_app(sdk)

  runner = web.AppRunner(app, shutdown_timeout=1.0)
  await runner.setup()

  # Remove stale socket file so UnixSite can bind.
  try:
    os.unlink(socket_path)
  except FileNotFoundError:
    pass

  await web.UnixSite(runner, socket_path).start()
  log.info('gateway start  unix://%s', socket_path)
  print(f'Gateway  unix://{socket_path}', flush=True)

  stop = asyncio.Event()
  loop = asyncio.get_running_loop()

  def _on_signal() -> None:
    """Request graceful shutdown, then force exit on a second signal."""
    if stop.is_set():
      log.warning('forced exit')
      loop.stop()
    else:
      stop.set()

  for sig in (signal.SIGTERM, signal.SIGINT):
    loop.add_signal_handler(sig, _on_signal)

  try:
    await stop.wait()
  finally:
    log.info('gateway shutting down')
    await runner.cleanup()
    try:
      os.unlink(socket_path)
    except FileNotFoundError:
      pass
    log.info('gateway stopped')
