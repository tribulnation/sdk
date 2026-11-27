"""Private order-event upstreams over KuCoin's authenticated WebSocket connections.

Classic: each product line has one connection opened with a private bullet token (the
typed client's transport fetches the token, pings at the server's interval and opens a
fresh connection after a drop). One all-symbol order channel per line feeds every
market's fill stream: spot `/spotMarket/tradeOrdersV2`, futures
`/contractMarket/tradeOrders`.

Unified Trading Account: one signature-authenticated connection
(`wss://wsapi-push.kucoin.com`) and one all-symbol `execution` channel feed every spot
and perpetual market's fill stream.
"""

from typing_extensions import AsyncIterable, AsyncIterator

from tribulnation.sdk.core import Subscription, exception_wrapper
from .common import Feed, OrderEvent, Shared

wrap_exceptions = exception_wrapper()


@wrap_exceptions
async def translated(stream: AsyncIterable[OrderEvent]) -> AsyncIterator[OrderEvent]:
  """Translate failures raised while iterating (a dropped connection), not only setup."""
  async for item in stream:
    yield item


@wrap_exceptions
async def connect_orders(
  shared: Shared, feed: Feed
) -> Subscription.Context[OrderEvent]:
  """Subscribe to the feed's all-symbol private channel.

  Raises:
    AuthError: The client was built without credentials.
  """
  match feed:
    case 'spot':
      stream = await shared.client.streams.spot_margin_private.order_v2()
    case 'perp':
      stream = await shared.client.streams.futures_private.all_orders()
    case 'unified':
      stream = await shared.client.streams.uta_private.execution()
  return Subscription.Context(translated(stream), wrap_exceptions(stream.unsubscribe))
