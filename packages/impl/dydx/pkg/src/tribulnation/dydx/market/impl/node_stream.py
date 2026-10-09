"""The full node fill feed a dYdX client shares across its markets."""

from typing_extensions import (
  TYPE_CHECKING,
  AsyncContextManager,
  AsyncGenerator,
  AsyncIterable,
)
from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio
import logging

from typed_dydx.chain import Chain
from typed_dydx.protos.dydxprotocol import subaccounts
from typed_dydx.protos.dydxprotocol.clob import StreamOrderbookUpdatesResponse
from tribulnation.sdk.core import Subscription

from .node_fills import (
  FillParser,
  NodeFill,
  PendingDeleveraging,
  deleveraging_matches,
  resolve_deleveraging,
)
from .orders import MAX_SUBACCOUNT

if TYPE_CHECKING:
  from .mixin import Shared

log = logging.getLogger(__name__)

RECONNECT_MIN = 0.5
"""Seconds before the first reconnection attempt."""
RECONNECT_MAX = 10.0
"""Cap of the exponential reconnection backoff, in seconds."""
BLOCK_RESULTS_ATTEMPTS = 5
"""Tries to read a block's deleveraging events before dropping its deleveraging fills."""


def subaccount_ids(address: str, parent: int) -> list[subaccounts.SubaccountId]:
  """The parent subaccount and every child it can have (`parent + 128 * k`)."""
  return [
    subaccounts.SubaccountId(owner=address, number=number)
    for number in range(parent, MAX_SUBACCOUNT + 1, 128)
  ]


def stream_updates(
  node: Chain,
  *,
  clob_pair_ids: list[int],
  subaccount_ids: list[subaccounts.SubaccountId],
) -> AsyncContextManager[AsyncIterable[StreamOrderbookUpdatesResponse]]:
  """The node's `StreamOrderbookUpdates`, filtered to `subaccount_ids`: the one place the
  stream is opened.

  Entering raises `typed_core` errors when the node rejects or cannot serve the stream;
  iterating raises them on transport failures, and ends without one when the node drops
  the subscription (e.g. a subscriber too slow for its buffer).
  """
  return node.clob.stream_orderbook_updates(
    clob_pair_id=clob_pair_ids,
    subaccount_ids=subaccount_ids,
    filter_orders_by_subaccount_id=True,
  )


def require_full_node(shared: 'Shared') -> Chain:
  """The chain client of the account's full node.

  Raises:
    ValueError: When the account does not configure both of its endpoints.
  """
  if shared.full_node is None:
    raise ValueError(
      "dYdX trades_source 'node' and 'fastest' need the account's full node endpoints: "
      'set both `full_node_grpc` (e.g. "host:9090") and `full_node_rpc` '
      '(e.g. "http://host:26657") on `accounts.Dydx`.'
    )
  return shared.full_node


@dataclass
class NodeFeed:
  """Our finalized fills from one full node stream, reconnecting forever.

  One `StreamOrderbookUpdates` subscription covers every CLOB pair the indexer lists
  when it connects (a market listed later is covered from the next reconnection) and the
  parent subaccount with all its children, filtered server-side to them
  (`filter_orders_by_subaccount_id`, which needs a node with the v4-chain#3414 fix).
  Connecting costs one snapshot of every book (a few MB); after that only our own
  updates flow.

  The feed never fails: a transport error, a node rejection or a stream the node ends
  is retried with exponential backoff, and fills finalized meanwhile are missed. Blocks
  already read are not re-emitted after a reconnection.
  """

  shared: 'Shared'
  node: Chain
  address: str
  clob_pairs: dict[int, int] = field(default_factory=dict[int, int])
  """CLOB pair id by perpetual id, for deleveraging fills; loaded when first needed."""

  async def fills(self) -> AsyncGenerator[NodeFill, None]:
    """Every fill of ours, as the node finalizes it."""
    parser = FillParser(self.address, self.shared.parent_subaccount)
    delay = RECONNECT_MIN
    while True:
      parser.reconnected()
      try:
        markets = await self.shared.load_markets()
        async with stream_updates(
          self.node,
          clob_pair_ids=sorted({int(m['clobPairId']) for m in markets.values()}),
          subaccount_ids=subaccount_ids(self.address, self.shared.parent_subaccount),
        ) as stream:
          async for response in stream:
            delay = RECONNECT_MIN
            received = datetime.now(timezone.utc)
            pending: list[PendingDeleveraging] = []
            for update in response.updates:
              try:
                items = parser.parse(update, received=received)
              except Exception:
                log.exception(
                  'Unreadable dYdX full node fill at %d', update.block_height
                )
                continue
              for item in items:
                if isinstance(item, NodeFill):
                  yield item
                else:
                  pending.append(item)
            for height in sorted({p.height for p in pending}):
              for fill in await self.deleveraging(
                [p for p in pending if p.height == height]
              ):
                yield fill
        log.warning('dYdX full node stream ended; resubscribing')
      except asyncio.CancelledError:
        raise
      except Exception as e:
        log.warning('dYdX full node stream failed: %r; retrying in %.1fs', e, delay)
        self.node.grpc_client.close()
      await asyncio.sleep(delay)
      delay = min(delay * 2, RECONNECT_MAX)

  async def perpetual_clob_pairs(self, *, refetch: bool) -> dict[int, int]:
    """CLOB pair id by perpetual id, from the chain."""
    if refetch or not self.clob_pairs:
      pairs = await self.node.clob.clob_pairs_paged()
      self.clob_pairs = {
        pair.perpetual_clob_metadata.perpetual_id: pair.id
        for pair in pairs
        if pair.perpetual_clob_metadata is not None
      }
    return self.clob_pairs

  async def deleveraging(self, pending: list[PendingDeleveraging]) -> list[NodeFill]:
    """Price one block's deleveraging fills from its `match` events.

    Retries with backoff; after `BLOCK_RESULTS_ATTEMPTS` failures the fills are logged
    and dropped.
    """
    height = pending[0].height
    error: Exception | None = None
    for attempt in range(BLOCK_RESULTS_ATTEMPTS):
      try:
        results = await self.node.comet.block_results(height, validate=False)
        pairs = await self.perpetual_clob_pairs(refetch=attempt > 0)
        return resolve_deleveraging(
          pending, deleveraging_matches(results), clob_pair_ids=pairs
        )
      except asyncio.CancelledError:
        raise
      except Exception as e:
        error = e
        await asyncio.sleep(0.2 * 2**attempt)
    log.error(
      'Dropping %d dYdX deleveraging fills at height %d: %r',
      len(pending),
      height,
      error,
    )
    return []


def node_fill_subscription(shared: 'Shared') -> Subscription[NodeFill]:
  """The client's one node fill feed, fanned out to every market that streams it.

  Raises:
    ValueError: When the account has no full node endpoints.
  """
  node = require_full_node(shared)
  if shared.node_subscription is None:
    feed = NodeFeed(shared=shared, node=node, address=shared.require_address())

    async def subscribe():
      """Start the feed; its connection opens on the first read."""
      fills = feed.fills()

      async def unsubscribe():
        """Stop the feed and drop its connection."""
        await fills.aclose()
        node.grpc_client.close()

      return fills, unsubscribe

    shared.node_subscription = Subscription.of(subscribe)
  return shared.node_subscription
