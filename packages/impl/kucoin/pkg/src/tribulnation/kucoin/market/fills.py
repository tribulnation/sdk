"""Private order-event upstreams over KuCoin's authenticated WebSocket connections.

Each product line has one connection opened with a private bullet token (the typed
client's transport fetches the token, pings at the server's interval and opens a fresh
connection after a drop). One all-symbol order channel per line feeds every market's
fill stream: spot `/spotMarket/tradeOrdersV2`, futures `/contractMarket/tradeOrders`.
"""

from typing_extensions import AsyncIterable, AsyncIterator

from tribulnation.sdk.core import Subscription, exception_wrapper
from .common import OrderEvent, Scope, Shared

wrap_exceptions = exception_wrapper()


@wrap_exceptions
async def translated(stream: AsyncIterable[OrderEvent]) -> AsyncIterator[OrderEvent]:
  """Translate failures raised while iterating (a dropped connection), not only setup."""
  async for item in stream:
    yield item


@wrap_exceptions
async def connect_orders(
  shared: Shared, scope: Scope
) -> Subscription.Context[OrderEvent]:
  """Subscribe to the line's all-symbol private order channel.

  Raises:
    AuthError: The client was built without credentials.
  """
  if scope == 'spot':
    stream = await shared.client.streams.spot_margin_private.order_v2()
  else:
    stream = await shared.client.streams.futures_private.all_orders()
  return Subscription.Context(translated(stream), wrap_exceptions(stream.unsubscribe))
