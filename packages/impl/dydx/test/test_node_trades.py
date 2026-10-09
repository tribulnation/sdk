"""dYdX `trades_stream` from a full node: fill mapping, dedup, and source selection."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, AsyncIterator, cast
import asyncio

import pytest
from typed_dydx.chain.comet.schemas import BlockResultsResponse
from typed_dydx.indexer.schemas import PerpetualMarket
from typed_dydx.node.market import Market as TypedMarket
from typed_dydx.protos.dydxprotocol import clob, subaccounts
from typed_core.grpc import GrpcClient

from tribulnation.dydx.market.exchange import Exchange
from tribulnation.dydx.market.impl import node_stream
from tribulnation.dydx.market.impl.dedup import FillDedup, Source
from tribulnation.dydx.market.impl.mixin import MarketMixin, Shared
from tribulnation.dydx.market.impl.node_fills import (
  FillKey,
  FillParser,
  NodeFill,
  PendingDeleveraging,
  base_size,
  deleveraging_matches,
  node_key,
  node_trade,
  resolve_deleveraging,
  subticks_price,
)
from tribulnation.dydx.market.impl.orders import (
  indexer_order_id,
  indexer_subaccount_id,
  serialize_id,
)
from tribulnation.dydx.market.impl.trades import indexer_key, trades_stream
from tribulnation.sdk.core import Subscription
from tribulnation.sdk.market import Trade

ADDRESS = 'dydx1039f5sxkl0t39vxcsnmlu62ly22typdap0zkyn'
OTHER = 'dydx1other'
RECEIVED = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
MARKET = cast(
  PerpetualMarket,
  {
    'ticker': 'BTC-USD',
    'clobPairId': 0,
    'atomicResolution': -10,
    'quantumConversionExponent': -9,
    'stepBaseQuantums': 1_000_000,
    'subticksPerTick': 100_000,
  },
)
"""BTC-USD's conversion parameters: 1e-10 BTC per quantum, 1e-5 USD per subtick."""
ETH = cast(
  PerpetualMarket,
  {
    'ticker': 'ETH-USD',
    'clobPairId': 1,
    'atomicResolution': -9,
    'quantumConversionExponent': -9,
    'stepBaseQuantums': 1_000_000,
    'subticksPerTick': 100_000,
  },
)


def oid(
  client_id: int, *, owner: str = ADDRESS, number: int = 0, clob_pair: int = 0
) -> clob.OrderId:
  """A protocol order id."""
  return clob.OrderId(
    subaccount_id=subaccounts.SubaccountId(owner=owner, number=number),
    client_id=client_id,
    order_flags=64,
    clob_pair_id=clob_pair,
  )


def order(order_id: clob.OrderId, *, buy: bool, subticks: int) -> clob.Order:
  """A protocol order of 1 BTC at `subticks`."""
  return clob.Order(
    order_id=order_id,
    side=clob.OrderSide.BUY if buy else clob.OrderSide.SELL,
    quantums=10_000_000_000,
    subticks=subticks,
  )


def update(
  height: int, fill: clob.StreamOrderbookFill, *, exec_mode: int = 7
) -> clob.StreamUpdate:
  """A stream update carrying one fill."""
  return clob.StreamUpdate(block_height=height, exec_mode=exec_mode, order_fill=fill)


def match_orders(
  taker: clob.Order, makers: list[tuple[clob.Order, int]]
) -> clob.StreamOrderbookFill:
  """A regular match of `taker` against `(maker, fill quantums)` pairs."""
  return clob.StreamOrderbookFill(
    clob_match=clob.ClobMatch(
      match_orders=clob.MatchOrders(
        taker_order_id=taker.order_id,
        fills=[
          clob.MakerFill(maker_order_id=m.order_id, fill_amount=q) for m, q in makers
        ],
      )
    ),
    orders=[m for m, _ in makers] + [taker],
    fill_amounts=[q for _, q in makers] + [sum(q for _, q in makers)],
  )


def liquidation(
  liquidated: subaccounts.SubaccountId,
  makers: list[tuple[clob.Order, int]],
  *,
  is_buy: bool,
) -> clob.StreamOrderbookFill:
  """A liquidation of `liquidated` against makers; it has no order of its own."""
  return clob.StreamOrderbookFill(
    clob_match=clob.ClobMatch(
      match_perpetual_liquidation=clob.MatchPerpetualLiquidation(
        liquidated=liquidated,
        clob_pair_id=0,
        perpetual_id=0,
        total_size=sum(q for _, q in makers),
        is_buy=is_buy,
        fills=[
          clob.MakerFill(maker_order_id=m.order_id, fill_amount=q) for m, q in makers
        ],
      )
    ),
    orders=[m for m, _ in makers],
    fill_amounts=[q for _, q in makers],
  )


def deleveraging(
  liquidated: subaccounts.SubaccountId,
  fills: list[tuple[subaccounts.SubaccountId, int]],
) -> clob.StreamOrderbookFill:
  """A deleveraging match: no orders, no price."""
  return clob.StreamOrderbookFill(
    clob_match=clob.ClobMatch(
      match_perpetual_deleveraging=clob.MatchPerpetualDeleveraging(
        liquidated=liquidated,
        perpetual_id=0,
        fills=[
          clob.MatchPerpetualDeleveragingFill(offsetting_subaccount_id=o, fill_amount=q)
          for o, q in fills
        ],
      )
    ),
  )


def us(number: int = 0) -> subaccounts.SubaccountId:
  """One of our subaccounts."""
  return subaccounts.SubaccountId(owner=ADDRESS, number=number)


def them(number: int = 0) -> subaccounts.SubaccountId:
  """Someone else's subaccount."""
  return subaccounts.SubaccountId(owner=OTHER, number=number)


def parse(parser: FillParser, *updates: clob.StreamUpdate) -> list[NodeFill]:
  """Every node fill (deleveraging excluded) the updates yield."""
  out: list[NodeFill] = []
  for u in updates:
    out += [f for f in parser.parse(u, received=RECEIVED) if isinstance(f, NodeFill)]
  return out


def trades(fills: list[NodeFill]) -> list[Trade]:
  """Fills as BTC-USD trades."""
  return [node_trade(f, MARKET) for f in fills]


# ── Conversions ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
  ('market', 'size', 'price'),
  [(MARKET, '0.0123', '60123'), (ETH, '1.5', '2345.6'), (MARKET, '1', '42')],
)
def test_conversions_invert_typed_order_conversion(
  market: PerpetualMarket, size: str, price: str
):
  """Quantums and subticks convert back to the size and price orders were built from."""
  typed = TypedMarket.from_payload(market)
  assert base_size(typed.calculate_quantums(size), market) == Decimal(size)
  assert subticks_price(typed.calculate_subticks(price), market) == Decimal(price)


def test_indexer_order_id_matches_recorded_order():
  """The indexer's order id derives from the protocol id (typed-dev's recording)."""
  order_id = clob.OrderId(
    subaccount_id=us(),
    client_id=32124288,
    order_flags=0,
    clob_pair_id=94,
  )
  assert indexer_order_id(order_id) == '70c72898-7ba8-5199-acdf-c7a07c85a7d3'


# ── Parsing ─────────────────────────────────────────────────────────────────


def test_only_finalized_fills_are_read():
  """Optimistic (< 7) and post-commit (102) copies of a fill are ignored."""
  mine = order(oid(1), buy=True, subticks=6_000_000_000)
  taker = order(oid(9, owner=OTHER), buy=False, subticks=5_900_000_000)
  fill = match_orders(taker, [(mine, 10_000_000)])
  parser = FillParser(ADDRESS, 0)
  assert parse(parser, update(10, fill, exec_mode=0)) == []
  assert parse(parser, update(10, fill, exec_mode=102)) == []
  assert len(parse(parser, update(10, fill, exec_mode=7))) == 1


def test_maker_fill_is_priced_at_our_order():
  """As maker we fill at our own price, with our order id and side."""
  mine = order(oid(1), buy=True, subticks=6_000_000_000)
  taker = order(oid(9, owner=OTHER), buy=False, subticks=5_900_000_000)
  [trade] = trades(
    parse(FillParser(ADDRESS, 0), update(10, match_orders(taker, [(mine, 25_000_000)])))
  )
  assert trade.order_id == serialize_id(oid(1))
  assert (trade.price, trade.qty, trade.maker) == (
    Decimal('60000'),
    Decimal('0.0025'),
    True,
  )
  assert trade.fee is None and trade.time == RECEIVED
  assert trade.id == f'10:{serialize_id(oid(1))}:0'
  assert trade.details == {
    'source': 'node',
    'height': 10,
    'exec_mode': 7,
    'kind': 'order',
    'subaccount': 0,
  }


def test_taker_fill_against_two_makers_is_two_partial_trades():
  """As taker, each maker fill is a trade at that maker's price."""
  mine = order(oid(1), buy=False, subticks=5_000_000_000)
  a = order(oid(7, owner=OTHER), buy=True, subticks=6_100_000_000)
  b = order(oid(8, owner=OTHER), buy=True, subticks=6_050_000_000)
  got = trades(
    parse(
      FillParser(ADDRESS, 0),
      update(10, match_orders(mine, [(a, 10_000_000), (b, 30_000_000)])),
    )
  )
  assert [(t.price, t.qty, t.maker) for t in got] == [
    (Decimal('61000'), Decimal('-0.001'), False),
    (Decimal('60500'), Decimal('-0.003'), False),
  ]
  assert [t.id for t in got] == [
    f'10:{serialize_id(oid(1))}:0',
    f'10:{serialize_id(oid(1))}:1',
  ]


def test_several_fills_of_one_order_in_one_block_get_distinct_ids():
  """Two matches of one maker order in a block count up; the next block restarts."""
  mine = order(oid(1, number=128), buy=True, subticks=6_000_000_000)
  t1 = order(oid(8, owner=OTHER), buy=False, subticks=1)
  t2 = order(oid(9, owner=OTHER), buy=False, subticks=1)
  parser = FillParser(ADDRESS, 0)
  got = parse(
    parser,
    update(10, match_orders(t1, [(mine, 10_000_000)])),
    update(10, match_orders(t2, [(mine, 10_000_000)])),
    update(11, match_orders(t1, [(mine, 10_000_000)])),
  )
  sdk_id = serialize_id(oid(1, number=128))
  assert [f.id for f in got] == [f'10:{sdk_id}:0', f'10:{sdk_id}:1', f'11:{sdk_id}:0']
  assert {f.subaccount for f in got} == {128}


def test_other_parents_and_owners_are_not_ours():
  """Only the parent and its children (`parent + 128 k`) are ours."""
  parser = FillParser(ADDRESS, 0)
  taker = order(oid(9, owner=OTHER), buy=False, subticks=1)
  for maker_id in [oid(1, number=1), oid(1, owner=OTHER)]:
    maker = order(maker_id, buy=True, subticks=6_000_000_000)
    assert parse(parser, update(10, match_orders(taker, [(maker, 1)]))) == []


def test_self_trade_across_subaccounts_is_both_sides():
  """Our taker against our own child's maker order: two trades, one per side."""
  maker = order(oid(1, number=128), buy=True, subticks=6_000_000_000)
  taker = order(oid(2), buy=False, subticks=1)
  got = trades(
    parse(
      FillParser(ADDRESS, 0), update(10, match_orders(taker, [(maker, 10_000_000)]))
    )
  )
  assert sorted((t.qty, t.maker) for t in got) == [
    (Decimal('-0.001'), False),
    (Decimal('0.001'), True),
  ]


def test_we_are_liquidated():
  """Liquidated, we fill once per maker fill, at its price, without an order."""
  a = order(oid(7, owner=OTHER), buy=True, subticks=5_000_000_000)
  b = order(oid(8, owner=OTHER), buy=True, subticks=4_990_000_000)
  got = parse(
    FillParser(ADDRESS, 0),
    update(10, liquidation(us(128), [(a, 10_000_000), (b, 20_000_000)], is_buy=False)),
  )
  assert [(f.kind, f.subaccount) for f in got] == [('liquidated', 128)] * 2
  assert [(t.order_id, t.price, t.qty, t.maker) for t in trades(got)] == [
    (None, Decimal('50000'), Decimal('-0.001'), False),
    (None, Decimal('49900'), Decimal('-0.002'), False),
  ]
  assert [f.id for f in got] == ['10:128:liquidated:0:0', '10:128:liquidated:0:1']


def test_maker_against_a_liquidation():
  """Our order filled by a liquidation taker is a plain maker fill."""
  mine = order(oid(1), buy=True, subticks=5_000_000_000)
  [trade] = trades(
    parse(
      FillParser(ADDRESS, 0),
      update(10, liquidation(them(), [(mine, 10_000_000)], is_buy=False)),
    )
  )
  assert (trade.order_id, trade.price, trade.qty, trade.maker) == (
    serialize_id(oid(1)),
    Decimal('50000'),
    Decimal('0.001'),
    True,
  )


def test_reconnection_skips_blocks_already_read():
  """After a reconnection, fills of blocks read before are not emitted again."""
  mine = order(oid(1), buy=True, subticks=6_000_000_000)
  taker = order(oid(9, owner=OTHER), buy=False, subticks=1)
  fill = match_orders(taker, [(mine, 10_000_000)])
  parser = FillParser(ADDRESS, 0)
  assert len(parse(parser, update(10, fill))) == 1
  parser.reconnected()
  assert parse(parser, update(10, fill)) == []
  assert len(parse(parser, update(11, fill))) == 1


# ── Deleveraging ────────────────────────────────────────────────────────────


def match_event(
  *,
  liquidated: tuple[str, int],
  offsetting: tuple[str, int],
  liquidated_quantums: int,
  quote: int,
  deleverage: bool = True,
) -> dict[str, Any]:
  """A CometBFT `match` event as `ProcessDeleveraging` emits it (mainnet encoding)."""
  values = {
    'taker_subaccount': liquidated[0],
    'taker_subaccount_number': str(liquidated[1]),
    'maker_subaccount': offsetting[0],
    'maker_subaccount_number': str(offsetting[1]),
    'taker_order_fee_quote_quantums': '0',
    'maker_order_fee_quote_quantums': '0',
    'taker_quote_balance_delta_quote_quantums': str(quote),
    'maker_quote_balance_delta_quote_quantums': str(-quote),
    'taker_perpetual_quantums_delta_base_quantums': str(liquidated_quantums),
    'maker_perpetual_quantums_delta_base_quantums': str(-liquidated_quantums),
    'insurance_fund_delta_quote_quantums': '0',
    'is_liquidation': 'false',
    'is_deleverage': 'true' if deleverage else 'false',
    'perpetual_id': '0',
    'msg_index': '0',
  }
  return {
    'type': 'match',
    'attributes': [{'key': k, 'value': v, 'index': True} for k, v in values.items()],
  }


def block_results(*events: dict[str, Any]) -> BlockResultsResponse:
  """Block results with the events in the operations transaction."""
  return cast(
    BlockResultsResponse,
    {
      'height': 10,
      'txs_results': [{'events': []}, {'events': list(events)}],
      'finalize_block_events': [],
    },
  )


def test_deleveraging_copies_stand_for_one_fill_each():
  """A match with two fills streams twice; copy `k` is fill `k`."""
  match = deleveraging(us(), [(them(1), 10_000_000), (them(2), 30_000_000)])
  parser = FillParser(ADDRESS, 0)
  got = [
    p for u in (update(10, match),) * 2 for p in parser.parse(u, received=RECEIVED)
  ]
  assert all(isinstance(p, PendingDeleveraging) for p in got)
  pending = cast(list[PendingDeleveraging], got)
  assert [(p.kind, p.quantums, p.offsetting.number) for p in pending] == [
    ('deleveraged', 10_000_000, 1),
    ('deleveraged', 30_000_000, 2),
  ]


def test_deleveraged_and_offsetting_fills_take_side_and_price_from_the_event():
  """Side and price come from the block's `match` events, matched by subaccounts and
  size: our long position deleveraged sells; offsetting a short that is deleveraged
  (it buys), we sell."""
  parser = FillParser(ADDRESS, 0)
  pending = [
    p
    for u in [
      update(10, deleveraging(us(), [(them(1), 10_000_000)])),
      update(10, deleveraging(them(5), [(us(128), 20_000_000)])),
    ]
    for p in parser.parse(u, received=RECEIVED)
    if isinstance(p, PendingDeleveraging)
  ]
  results = block_results(
    match_event(  # a liquidation match on the way: not a deleveraging
      liquidated=(ADDRESS, 0),
      offsetting=(OTHER, 1),
      liquidated_quantums=-10_000_000,
      quote=999,
      deleverage=False,
    ),
    match_event(
      liquidated=(ADDRESS, 0),
      offsetting=(OTHER, 1),
      liquidated_quantums=-10_000_000,
      quote=60_000_000,
    ),
    match_event(
      liquidated=(OTHER, 5),
      offsetting=(ADDRESS, 128),
      liquidated_quantums=20_000_000,
      quote=-118_000_000,
    ),
  )
  fills = resolve_deleveraging(
    pending, deleveraging_matches(results), clob_pair_ids={0: 0}
  )
  got = trades(fills)
  assert [(f.kind, f.subaccount) for f in fills] == [
    ('deleveraged', 0),
    ('offsetting', 128),
  ]
  assert [(t.order_id, t.price, t.qty, t.maker) for t in got] == [
    (None, Decimal('60000'), Decimal('-0.001'), False),
    (None, Decimal('59000'), Decimal('-0.002'), True),
  ]


def test_deleveraging_without_its_event_raises():
  """A fill no event accounts for is an error, not a guess."""
  [p] = FillParser(ADDRESS, 0).parse(
    update(10, deleveraging(us(), [(them(1), 10_000_000)])), received=RECEIVED
  )
  assert isinstance(p, PendingDeleveraging)
  with pytest.raises(ValueError, match='No deleveraging match event'):
    resolve_deleveraging([p], [], clob_pair_ids={0: 0})


# ── Dedup ───────────────────────────────────────────────────────────────────


def test_dedup_admits_the_first_copy_from_either_source():
  """Each fill passes once, whichever source is first; a second identical fill in the
  block is a second fill."""
  key = FillKey(10, 'order:x', Decimal('1'))
  orders: list[tuple[Source, Source]] = [('node', 'indexer'), ('indexer', 'node')]
  for first, second in orders:
    dedup = FillDedup()
    assert dedup.admit(first, key)
    assert not dedup.admit(second, key)
    assert dedup.admit(first, key)
    assert not dedup.admit(second, key)
    assert dedup.admit(second, key)


def test_dedup_forgets_old_blocks_and_drops_their_late_copies():
  """Keys older than the window are dropped, as are copies arriving that late."""
  dedup = FillDedup(window=10)
  assert dedup.admit('node', FillKey(10, 'order:x', Decimal('1')))
  assert dedup.admit('node', FillKey(25, 'order:y', Decimal('1')))
  assert 10 not in dedup.seen
  assert not dedup.admit('indexer', FillKey(10, 'order:x', Decimal('1')))
  assert dedup.admit('indexer', None)


def test_node_and_indexer_keys_agree():
  """A node fill and its indexer copy share a key, for orders and orderless fills."""
  mine = order(oid(1, number=128), buy=True, subticks=6_000_000_000)
  taker = order(oid(9, owner=OTHER), buy=False, subticks=1)
  [order_fill] = parse(
    FillParser(ADDRESS, 0), update(10, match_orders(taker, [(mine, 10_000_000)]))
  )
  indexer_order: Any = {
    'createdAtHeight': 10,
    'orderId': indexer_order_id(oid(1, number=128)),
    'size': Decimal('0.0010'),
    'side': 'BUY',
    'subaccountId': indexer_subaccount_id(ADDRESS, 128),
    'clobPairId': 0,
  }
  assert node_key(order_fill, MARKET, address=ADDRESS) == indexer_key(indexer_order)
  maker = order(oid(7, owner=OTHER), buy=True, subticks=5_000_000_000)
  [liquidated] = parse(
    FillParser(ADDRESS, 0),
    update(10, liquidation(us(), [(maker, 10_000_000)], is_buy=False)),
  )
  indexer_liquidated: Any = {
    'createdAtHeight': 10,
    'size': Decimal('0.001'),
    'side': 'SELL',
    'subaccountId': indexer_subaccount_id(ADDRESS, 0),
    'clobPairId': 0,
  }
  assert node_key(liquidated, MARKET, address=ADDRESS) == indexer_key(
    indexer_liquidated
  )


# ── Streams ─────────────────────────────────────────────────────────────────


def node_fill(height: int = 10, *, client_id: int = 1) -> NodeFill:
  """A finalized BTC-USD maker fill of ours: buy 0.001 at 60000."""
  return NodeFill(
    height=height,
    exec_mode=7,
    clob_pair_id=0,
    kind='order',
    subaccount=0,
    order_id=oid(client_id),
    side='BUY',
    quantums=10_000_000,
    subticks=6_000_000_000,
    maker=True,
    id=f'{height}:{client_id}:0',
    received=RECEIVED,
  )


def indexer_message(height: int = 10, *, client_id: int = 1) -> dict[str, Any]:
  """The indexer's copy of `node_fill`."""
  return {
    'fills': [
      {
        'id': f'indexer-{height}-{client_id}',
        'ticker': 'BTC-USD',
        'side': 'BUY',
        'price': Decimal('60000'),
        'size': Decimal('0.001'),
        'createdAt': RECEIVED,
        'createdAtHeight': height,
        'liquidity': 'MAKER',
        'type': 'LIMIT',
        'orderId': indexer_order_id(oid(client_id)),
        'subaccountId': indexer_subaccount_id(ADDRESS, 0),
        'clobPairId': 0,
      }
    ]
  }


class Gate:
  """Release items of a fake upstream in a chosen order."""

  def __init__(self):
    self.events = {name: asyncio.Event() for name in ('node', 'indexer')}

  async def stream(self, name: str, items: list[Any]) -> AsyncIterator[Any]:
    """Yield `items` once the gate for `name` opens, then idle like a live feed."""
    await self.events[name].wait()
    for item in items:
      yield item
    await asyncio.Event().wait()


def market_with(
  *, node: AsyncIterator[NodeFill] | None, indexer: AsyncIterator[Any] | None
) -> MarketMixin:
  """A BTC-USD market whose node and indexer feeds are fakes."""
  exchange = Exchange.new(
    address=ADDRESS,
    public=True,
    full_node_grpc='127.0.0.1:1',
    full_node_rpc='http://127.0.0.1:2',
  )
  shared = exchange.shared

  async def noop():
    """Nothing to release."""

  if node is not None:
    node_iter = node

    async def subscribe_node():
      """The fake node feed."""
      return node_iter, noop

    shared.node_subscription = Subscription.of(subscribe_node)
  if indexer is not None:
    indexer_iter = indexer

    async def subscribe_indexer():
      """The fake indexer channel."""
      return indexer_iter, noop

    shared.parent_subaccount_subscriptions[0] = Subscription.of(subscribe_indexer)
  return MarketMixin(shared=shared, perpetual_market=MARKET)


async def take(stream: AsyncIterator[Trade], n: int) -> list[Trade]:
  """The first `n` trades, failing rather than hanging."""
  return [await asyncio.wait_for(anext(stream), 2) for _ in range(n)]


@pytest.mark.parametrize('first', ['node', 'indexer'])
async def test_fastest_emits_each_fill_once_from_the_first_source(first: Source):
  """Whichever source delivers a fill first wins; its copy from the other is dropped."""
  gate = Gate()
  market = market_with(
    node=gate.stream('node', [node_fill(10), node_fill(11, client_id=2)]),
    indexer=gate.stream(
      'indexer', [indexer_message(10), indexer_message(11, client_id=2)]
    ),
  )
  settings: Any = {'dydx': {'trades_source': 'fastest'}}
  async with trades_stream(market, settings=settings) as stream:
    it = aiter(stream)
    gate.events[first].set()
    got = await take(it, 2)
    gate.events['indexer' if first == 'node' else 'node'].set()
    with pytest.raises(asyncio.TimeoutError):
      await asyncio.wait_for(anext(it), 0.2)
  assert [cast(dict[str, Any], t.details)['source'] for t in got] == [first] * 2
  assert [t.qty for t in got] == [Decimal('0.001')] * 2


async def test_fastest_keeps_delivering_while_the_node_is_down():
  """With no node fills at all, the indexer's arrive."""
  gate = Gate()
  gate.events['indexer'].set()
  market = market_with(
    node=gate.stream('node', []),
    indexer=gate.stream('indexer', [indexer_message(10), indexer_message(11)]),
  )
  settings: Any = {'dydx': {'trades_source': 'fastest'}}
  async with trades_stream(market, settings=settings) as stream:
    got = await take(aiter(stream), 2)
  assert [t.id for t in got] == ['indexer-10-1', 'indexer-11-1']


async def test_node_source_filters_to_its_market():
  """`'node'` streams this market's node fills only."""
  other = replace(node_fill(10), clob_pair_id=1, id='eth')

  async def fills() -> AsyncIterator[NodeFill]:
    """Two markets' fills."""
    yield other
    yield node_fill(10)
    await asyncio.Event().wait()

  market = market_with(node=fills(), indexer=None)
  settings: Any = {'dydx': {'trades_source': 'node'}}
  async with trades_stream(market, settings=settings) as stream:
    [trade] = await take(aiter(stream), 1)
  assert trade.id == '10:1:0' and trade.price == Decimal('60000')


@pytest.mark.parametrize('source', ['node', 'fastest'])
async def test_node_sources_need_the_full_node_endpoints(source: str):
  """Without `full_node_grpc`/`full_node_rpc`, opening the stream says what is missing."""
  market = MarketMixin(
    shared=Exchange.new(address=ADDRESS, public=True).shared, perpetual_market=MARKET
  )
  settings: Any = {'dydx': {'trades_source': source}}
  with pytest.raises(ValueError, match='full_node_grpc'):
    async with trades_stream(market, settings=settings):
      pass


def test_endpoints_build_an_owned_node_chain_client():
  """Both endpoints make one chain client of the node (plaintext gRPC plus CometBFT),
  owned with the client; either alone makes none."""
  shared = Exchange.new(
    address=ADDRESS,
    public=True,
    full_node_grpc='20.222.23.181:9090',
    full_node_rpc='http://20.222.23.181:26657/',
  ).shared
  node = shared.full_node
  assert node is not None
  grpc: GrpcClient = node.grpc_client
  assert (grpc.host, grpc.port, grpc.ssl) == ('20.222.23.181', 9090, False)
  assert node.comet_client.base_url == 'http://20.222.23.181:26657'
  assert len(list(shared.resources())) == 2
  half = Exchange.new(address=ADDRESS, public=True, full_node_grpc='h:1').shared
  assert half.full_node is None and len(list(half.resources())) == 1


# ── The feed ────────────────────────────────────────────────────────────────


class FakeComet:
  """CometBFT RPC returning fixed block results."""

  def __init__(self, results: BlockResultsResponse):
    self.results = results
    self.heights: list[int] = []

  async def block_results(self, height: int, *, validate: bool | None = None):
    """Record and answer."""
    self.heights.append(height)
    return self.results


async def test_feed_reconnects_and_resolves_deleveraging(
  monkeypatch: pytest.MonkeyPatch,
):
  """The feed survives a failing and an ending stream, never re-emits a block, and
  prices deleveraging fills from `block_results`."""
  monkeypatch.setattr(node_stream, 'RECONNECT_MIN', 0)
  mine = order(oid(1), buy=True, subticks=6_000_000_000)
  taker = order(oid(9, owner=OTHER), buy=False, subticks=1)
  regular = update(10, match_orders(taker, [(mine, 10_000_000)]))
  delev = update(12, deleveraging(us(), [(them(1), 10_000_000)]))
  connections: list[list[clob.StreamUpdate] | Exception] = [
    [regular],  # then the node ends the stream
    RuntimeError('connection refused'),
    [regular, delev],  # height 10 again after reconnecting: skipped
  ]
  requests: list[dict[str, Any]] = []

  async def fake_stream(node: Any, **request: Any):
    """Serve one scripted connection."""
    requests.append(request)
    script = connections.pop(0)
    if isinstance(script, Exception):
      raise script
    yield clob.StreamOrderbookUpdatesResponse(updates=script)
    if not connections:
      await asyncio.Event().wait()

  monkeypatch.setattr(node_stream, 'stream_updates', fake_stream)
  shared = Exchange.new(
    address=ADDRESS,
    public=True,
    full_node_grpc='127.0.0.1:1',
    full_node_rpc='http://127.0.0.1:2',
  ).shared
  shared.perpetual_markets = {'BTC-USD': MARKET, 'ETH-USD': ETH}
  comet = FakeComet(
    block_results(
      match_event(
        liquidated=(ADDRESS, 0),
        offsetting=(OTHER, 1),
        liquidated_quantums=-10_000_000,
        quote=60_000_000,
      )
    )
  )
  node = SimpleNamespace(comet=comet, grpc_client=GrpcClient(host='127.0.0.1', port=1))
  feed = node_stream.NodeFeed(
    shared=cast(Shared, shared),
    node=cast(Any, node),
    address=ADDRESS,
    clob_pairs={0: 0},
  )
  fills = feed.fills()
  got = [await asyncio.wait_for(anext(fills), 2) for _ in range(2)]
  await fills.aclose()
  assert [(f.height, f.kind) for f in got] == [(10, 'order'), (12, 'deleveraged')]
  assert comet.heights == [12]
  assert requests[0]['clob_pair_ids'] == [0, 1]
  assert len(requests[0]['subaccount_ids']) == 1001


async def test_account_endpoints_reach_the_market():
  """`accounts.Dydx` endpoints thread through `MarketSDK` to the client's `Shared`."""
  from tribulnation.sdk import MarketSDK, accounts

  sdk = MarketSDK(
    {
      'd': accounts.Dydx(
        address=ADDRESS,
        public=True,
        full_node_grpc='10.0.0.1:9090',
        full_node_rpc='http://10.0.0.1:26657',
      ),
      'plain': accounts.Dydx(address=ADDRESS, public=True),
    }
  )
  exchange = await sdk.all['d'].perp_exchange('perp')
  plain = await sdk.all['plain'].perp_exchange('perp')
  assert isinstance(exchange, Exchange) and isinstance(plain, Exchange)
  assert exchange.shared.full_node is not None
  assert exchange.shared.full_node.grpc_client.host == '10.0.0.1'
  assert plain.shared.full_node is None
