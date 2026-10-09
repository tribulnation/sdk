"""Our fills from a dYdX full node's `StreamOrderbookUpdates` stream, without I/O.

`FillParser` turns finalized stream updates into `NodeFill`s (or, for deleveraging,
`PendingDeleveraging`s that need the block's `match` events for side and price);
`deleveraging_matches` reads those events from CometBFT `block_results`; `node_trade`
converts a fill to an SDK `Trade` with the market's quantum and subtick conversion.

Protocol references (v4-chain `protocol/v9.7.1`):

- `x/clob/keeper/process_operations.go`: one `StreamOrderbookFill` per `MatchOrders` and
  `MatchPerpetualLiquidation`, but a `MatchPerpetualDeleveraging` is streamed once *per
  fill*, each copy carrying the whole match.
- `x/clob/memclob/memclob_grpc_streaming.go` (`GenerateStreamOrderbookFill`): `orders`
  holds the maker orders, then the taker order (absent for a liquidation);
  `fill_amounts` are cumulative and not used here.
- `x/clob/keeper/deleveraging.go` (`ProcessDeleveraging`): emits a CometBFT `match` event
  per deleveraging fill with the liquidated subaccount as taker and the offsetting one as
  maker, zero fees, and signed quote and perpetual deltas per side.
"""

from typing_extensions import Iterable, Iterator, Literal, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from typed_dydx.chain.comet.schemas import BlockResultsResponse, Event
from typed_dydx.indexer.schemas import PerpetualMarket
from typed_dydx.protos.dydxprotocol import clob, subaccounts
from tribulnation.sdk.market import Trade

from .orders import (
  MAX_SUBACCOUNT,
  indexer_order_id,
  indexer_subaccount_id,
  serialize_id,
)

EXEC_MODE_FINALIZE = 7
"""`StreamUpdate.exec_mode` of finalized updates (Cosmos SDK `ExecModeFinalize`)."""
QUOTE_EXPONENT = -6
"""USDC quote quantums are 1e-6 USDC."""

Side = Literal['BUY', 'SELL']
FillKind = Literal['order', 'liquidated', 'deleveraged', 'offsetting']
"""- `order`: a fill of one of our orders (as maker, as taker, or as maker against a
  liquidation).
- `liquidated`: our subaccount was liquidated against a maker order; no order of ours.
- `deleveraged`: our subaccount was deleveraged (the liquidated side); no order.
- `offsetting`: our subaccount was the offsetting side of a deleveraging; no order."""


@dataclass(frozen=True, kw_only=True)
class NodeFill:
  """One fill of ours from the node stream, before market conversion."""

  height: int
  """Block height of the finalized update."""
  exec_mode: int
  """`StreamUpdate.exec_mode`; always finalized here."""
  clob_pair_id: int
  kind: FillKind
  subaccount: int
  """Our subaccount number that filled."""
  order_id: clob.OrderId | None
  """Our order, for `kind == 'order'`."""
  side: Side
  quantums: int
  """Fill size in base quantums."""
  subticks: int | None = None
  """Fill price in subticks: the maker order's. `None` for deleveraging fills."""
  quote_quantums: int | None = None
  """Absolute quote amount of a deleveraging fill, for its price."""
  maker: bool
  id: str
  """Synthetic, deterministic fill id (see `FillParser`)."""


@dataclass(frozen=True, kw_only=True)
class PendingDeleveraging:
  """A deleveraging fill of ours whose side and price are in the block's events."""

  height: int
  exec_mode: int
  perpetual_id: int
  liquidated: subaccounts.SubaccountId
  offsetting: subaccounts.SubaccountId
  kind: Literal['deleveraged', 'offsetting']
  subaccount: int
  quantums: int
  id: str


@dataclass(frozen=True, kw_only=True)
class DeleveragingMatch:
  """A CometBFT `match` event of a deleveraging fill."""

  perpetual_id: int
  liquidated: tuple[str, int]
  """Taker subaccount, as `(owner, number)`."""
  offsetting: tuple[str, int]
  """Maker subaccount, as `(owner, number)`."""
  liquidated_quantums: int
  """Signed perpetual delta of the liquidated side, in base quantums."""
  offsetting_quantums: int
  """Signed perpetual delta of the offsetting side, in base quantums."""
  offsetting_quote: int
  """Signed quote delta of the offsetting side, in quote quantums (no fees)."""


def side_of(side: clob.OrderSide) -> Side:
  """The SDK side of a protocol order side."""
  if side == clob.OrderSide.BUY:
    return 'BUY'
  if side == clob.OrderSide.SELL:
    return 'SELL'
  raise ValueError(f'Unknown dYdX order side: {side}')


@dataclass
class FillParser:
  """Extract our finalized fills from a full node stream, one connection after another.

  Only finalized updates (`exec_mode == 7`) are read: optimistic ones (< 7) and those
  replayed after a commit (102, including snapshots) may be reverted or name a different
  maker than the block finalizes.

  Fill ids are synthetic, since the node has no fill id: `<height>:<subject>:<n>`,
  where the subject is our SDK order id for order fills and
  `<subaccount>:<kind>:<perpetual id>` for orderless ones, and `n` counts that subject's
  fills within the block, in stream order. They are deterministic for a given block and
  differ from the indexer's fill ids.
  """

  address: str
  parent: int
  """Parent subaccount; we own it and its children `parent + 128 * k`."""
  last_height: int = 0
  """Highest finalized height seen."""
  resume_after: int = 0
  """Heights at or below this were read on an earlier connection and are skipped."""
  counts: dict[str, int] = field(default_factory=dict[str, int])
  """Fills per subject in `last_height`."""
  deleveraging_copies: dict[bytes, int] = field(default_factory=dict[bytes, int])
  """Copies of each deleveraging match seen in `last_height`."""

  def ours(self, subaccount: subaccounts.SubaccountId | None) -> bool:
    """Whether a subaccount is the parent or one of its children."""
    return (
      subaccount is not None
      and subaccount.owner == self.address
      and subaccount.number % 128 == self.parent
      and subaccount.number <= MAX_SUBACCOUNT
    )

  def reconnected(self):
    """Start a new connection: blocks already read are not read again."""
    self.resume_after = self.last_height

  def next_id(self, height: int, subject: str) -> str:
    """The synthetic id of the next fill of `subject` in `height`."""
    n = self.counts.get(subject, 0)
    self.counts[subject] = n + 1
    return f'{height}:{subject}:{n}'

  def parse(self, update: clob.StreamUpdate) -> list[NodeFill | PendingDeleveraging]:
    """Our fills in one stream update; empty unless it is a finalized fill.

    Args:
      update: A `StreamOrderbookUpdatesResponse.updates` item.
    """
    fill = update.order_fill
    if (
      fill is None or fill.clob_match is None or update.exec_mode != EXEC_MODE_FINALIZE
    ):
      return []
    height = update.block_height
    if height <= self.resume_after:
      return []
    if height != self.last_height:
      self.last_height = height
      self.counts.clear()
      self.deleveraging_copies.clear()
    match = fill.clob_match
    if match.match_orders is not None:
      return list(self.match_orders(match.match_orders, fill, update))
    if match.match_perpetual_liquidation is not None:
      return list(
        self.match_liquidation(match.match_perpetual_liquidation, fill, update)
      )
    if match.match_perpetual_deleveraging is not None:
      return list(self.match_deleveraging(match.match_perpetual_deleveraging, update))
    return []

  def order_fill(
    self,
    order: clob.Order,
    *,
    maker_order: clob.Order,
    quantums: int,
    maker: bool,
    update: clob.StreamUpdate,
  ) -> NodeFill:
    """A fill of one of our orders, priced at the maker order."""
    order_id = order.order_id
    assert order_id is not None and order_id.subaccount_id is not None
    sdk_id = serialize_id(order_id)
    return NodeFill(
      height=update.block_height,
      exec_mode=update.exec_mode,
      clob_pair_id=order_id.clob_pair_id,
      kind='order',
      subaccount=order_id.subaccount_id.number,
      order_id=order_id,
      side=side_of(order.side),
      quantums=quantums,
      subticks=maker_order.subticks,
      maker=maker,
      id=self.next_id(update.block_height, sdk_id),
    )

  def match_orders(
    self,
    match: clob.MatchOrders,
    fill: clob.StreamOrderbookFill,
    update: clob.StreamUpdate,
  ) -> Iterator[NodeFill]:
    """Our fills in a regular match: as its taker, as one of its makers, or both."""
    orders = orders_by_id(fill.orders)
    taker_id = match.taker_order_id
    taker = orders.get(bytes(taker_id)) if taker_id is not None else None
    for maker_fill in match.fills:
      maker_id = maker_fill.maker_order_id
      maker = orders.get(bytes(maker_id)) if maker_id is not None else None
      if maker is None:
        raise ValueError(f'Stream fill at {update.block_height} misses a maker order')
      if taker_id is not None and self.ours(taker_id.subaccount_id):
        if taker is None:
          raise ValueError(
            f'Stream fill at {update.block_height} misses its taker order'
          )
        yield self.order_fill(
          taker,
          maker_order=maker,
          quantums=maker_fill.fill_amount,
          maker=False,
          update=update,
        )
      if maker_id is not None and self.ours(maker_id.subaccount_id):
        yield self.order_fill(
          maker,
          maker_order=maker,
          quantums=maker_fill.fill_amount,
          maker=True,
          update=update,
        )

  def match_liquidation(
    self,
    match: clob.MatchPerpetualLiquidation,
    fill: clob.StreamOrderbookFill,
    update: clob.StreamUpdate,
  ) -> Iterator[NodeFill]:
    """Our fills in a liquidation: as the liquidated taker (one per maker fill), or as a
    maker against it."""
    orders = orders_by_id(fill.orders)
    liquidated = match.liquidated
    for maker_fill in match.fills:
      maker_id = maker_fill.maker_order_id
      maker = orders.get(bytes(maker_id)) if maker_id is not None else None
      if maker is None:
        raise ValueError(f'Stream fill at {update.block_height} misses a maker order')
      if liquidated is not None and self.ours(liquidated):
        subject = f'{liquidated.number}:liquidated:{match.perpetual_id}'
        yield NodeFill(
          height=update.block_height,
          exec_mode=update.exec_mode,
          clob_pair_id=match.clob_pair_id,
          kind='liquidated',
          subaccount=liquidated.number,
          order_id=None,
          side='BUY' if match.is_buy else 'SELL',
          quantums=maker_fill.fill_amount,
          subticks=maker.subticks,
          maker=False,
          id=self.next_id(update.block_height, subject),
        )
      if maker_id is not None and self.ours(maker_id.subaccount_id):
        yield self.order_fill(
          maker,
          maker_order=maker,
          quantums=maker_fill.fill_amount,
          maker=True,
          update=update,
        )

  def match_deleveraging(
    self,
    match: clob.MatchPerpetualDeleveraging,
    update: clob.StreamUpdate,
  ) -> Iterator[PendingDeleveraging]:
    """Our side of the one deleveraging fill this copy of the match stands for.

    The node streams the whole match once per fill, in fill order, so the `k`-th copy of
    a match within a block is its fill `k` (modulo its fill count, should an identical
    match recur in the block).
    """
    if not match.fills or match.liquidated is None:
      return
    key = bytes(match)
    copy = self.deleveraging_copies.get(key, 0)
    self.deleveraging_copies[key] = copy + 1
    deleveraging_fill = match.fills[copy % len(match.fills)]
    offsetting = deleveraging_fill.offsetting_subaccount_id
    if offsetting is None:
      return
    roles: list[tuple[Literal['deleveraged', 'offsetting'], int]] = []
    if self.ours(match.liquidated):
      roles.append(('deleveraged', match.liquidated.number))
    if self.ours(offsetting):
      roles.append(('offsetting', offsetting.number))
    for kind, number in roles:
      yield PendingDeleveraging(
        height=update.block_height,
        exec_mode=update.exec_mode,
        perpetual_id=match.perpetual_id,
        liquidated=match.liquidated,
        offsetting=offsetting,
        kind=kind,
        subaccount=number,
        quantums=deleveraging_fill.fill_amount,
        id=self.next_id(update.block_height, f'{number}:{kind}:{match.perpetual_id}'),
      )


def orders_by_id(orders: Sequence[clob.Order]) -> dict[bytes, clob.Order]:
  """A stream fill's orders by their serialized protocol order id."""
  return {bytes(o.order_id): o for o in orders if o.order_id is not None}


def match_events(results: BlockResultsResponse) -> Iterator[Event]:
  """Every event in a block's results: its transactions' (the operations transaction
  carries the matches), then `FinalizeBlock`'s own."""
  for tx in results.get('txs_results') or []:
    yield from tx.get('events') or []
  yield from results.get('finalize_block_events') or []


def deleveraging_matches(results: BlockResultsResponse) -> list[DeleveragingMatch]:
  """The deleveraging `match` events of a block, in emission order.

  Attributes are plain strings (CometBFT 0.38), with signed integer deltas; the taker is
  the liquidated subaccount and the maker the offsetting one.
  """
  matches: list[DeleveragingMatch] = []
  for event in match_events(results):
    if event['type'] != 'match':
      continue
    attrs = {a['key']: a['value'] for a in event['attributes']}
    if attrs.get('is_deleverage') != 'true':
      continue
    matches.append(
      DeleveragingMatch(
        perpetual_id=int(attrs['perpetual_id']),
        liquidated=(attrs['taker_subaccount'], int(attrs['taker_subaccount_number'])),
        offsetting=(attrs['maker_subaccount'], int(attrs['maker_subaccount_number'])),
        liquidated_quantums=int(attrs['taker_perpetual_quantums_delta_base_quantums']),
        offsetting_quantums=int(attrs['maker_perpetual_quantums_delta_base_quantums']),
        offsetting_quote=int(attrs['maker_quote_balance_delta_quote_quantums']),
      )
    )
  return matches


def resolve_deleveraging(
  pending: Iterable[PendingDeleveraging],
  matches: Sequence[DeleveragingMatch],
  *,
  clob_pair_ids: Mapping[int, int],
) -> list[NodeFill]:
  """Price and side pending deleveraging fills of one block from its `match` events.

  A fill matches the first unused event (per kind, so a self-deleveraging consumes it
  once per side) with its perpetual, both subaccounts and absolute size.

  Args:
    pending: Pending fills, all of one block.
    matches: That block's deleveraging events (`deleveraging_matches`).
    clob_pair_ids: CLOB pair id by perpetual id.

  Raises:
    ValueError: When a fill has no matching event or its perpetual no CLOB pair.
  """
  used: dict[str, set[int]] = {'deleveraged': set(), 'offsetting': set()}
  fills: list[NodeFill] = []
  for p in pending:
    for i, m in enumerate(matches):
      if (
        i not in used[p.kind]
        and m.perpetual_id == p.perpetual_id
        and m.liquidated == (p.liquidated.owner, p.liquidated.number)
        and m.offsetting == (p.offsetting.owner, p.offsetting.number)
        and abs(m.liquidated_quantums) == p.quantums
      ):
        used[p.kind].add(i)
        break
    else:
      raise ValueError(f'No deleveraging match event for {p.id}')
    delta = m.liquidated_quantums if p.kind == 'deleveraged' else m.offsetting_quantums
    clob_pair_id = clob_pair_ids.get(p.perpetual_id)
    if clob_pair_id is None:
      raise ValueError(f'Unknown dYdX perpetual {p.perpetual_id}')
    fills.append(
      NodeFill(
        height=p.height,
        exec_mode=p.exec_mode,
        clob_pair_id=clob_pair_id,
        kind=p.kind,
        subaccount=p.subaccount,
        order_id=None,
        side='BUY' if delta > 0 else 'SELL',
        quantums=p.quantums,
        quote_quantums=abs(m.offsetting_quote),
        maker=p.kind == 'offsetting',
        id=p.id,
      )
    )
  return fills


def plain(value: Decimal) -> Decimal:
  """`value` without trailing zeros, in positional notation (`83072`, not `83072.00000`
  or `8.3072E+4`), as the indexer reports amounts."""
  normal = value.normalize()
  return normal.quantize(Decimal(1)) if normal == normal.to_integral_value() else normal


def base_size(quantums: int, market: PerpetualMarket) -> Decimal:
  """Base quantums in base units: the inverse of `typed_dydx` `calculate_quantums`."""
  return plain(Decimal(quantums).scaleb(market['atomicResolution']))


def subticks_price(subticks: int, market: PerpetualMarket) -> Decimal:
  """Subticks in quote units per base unit: the inverse of `typed_dydx`
  `calculate_subticks`."""
  exponent = (
    market['quantumConversionExponent'] - market['atomicResolution'] + QUOTE_EXPONENT
  )
  return plain(Decimal(subticks).scaleb(exponent))


def fill_price(fill: NodeFill, market: PerpetualMarket) -> Decimal:
  """A fill's price: its subticks, or a deleveraging's quote amount over its size."""
  if fill.subticks is not None:
    return subticks_price(fill.subticks, market)
  if fill.quote_quantums is None:
    raise ValueError(f'Fill {fill.id} has no price')
  quote = Decimal(fill.quote_quantums).scaleb(QUOTE_EXPONENT)
  return plain(quote / base_size(fill.quantums, market))


@dataclass(frozen=True)
class FillKey:
  """What identifies an economic fill on both the node and the indexer, for `'fastest'`.

  The indexer's order id is derived from the protocol order id (uuid5, as the indexer
  does), so a node fill and its indexer copy share a key without the indexer pushing the
  order alongside. Prices are left out: both sources must agree on them, and a rounding
  difference must not turn one fill into two.
  """

  height: int
  subject: str
  """`order:<indexer order id>` for order fills; for orderless ones
  `orderless:<indexer subaccount id>:<clob pair id>:<side>`."""
  size: Decimal
  """Absolute base size."""


def node_key(fill: NodeFill, market: PerpetualMarket, *, address: str) -> FillKey:
  """The dedup key of a node fill of `address`'s subaccounts."""
  size = base_size(fill.quantums, market)
  if fill.order_id is not None:
    return FillKey(fill.height, f'order:{indexer_order_id(fill.order_id)}', size)
  subaccount = indexer_subaccount_id(address, fill.subaccount)
  return FillKey(
    fill.height, f'orderless:{subaccount}:{fill.clob_pair_id}:{fill.side}', size
  )


def node_trade(fill: NodeFill, market: PerpetualMarket) -> Trade:
  """An SDK trade from a node fill.

  `time` is `None`: stream updates carry no block time, and waiting for it would delay
  the fill. `details['height']` is the fill's block height, from which the block time
  can be resolved later.
  """
  sign = 1 if fill.side == 'BUY' else -1
  return Trade(
    id=fill.id,
    order_id=serialize_id(fill.order_id) if fill.order_id is not None else None,
    price=fill_price(fill, market),
    qty=base_size(fill.quantums, market) * sign,
    time=None,
    maker=fill.maker,
    fee=None,
    details={
      'source': 'node',
      'height': fill.height,
      'exec_mode': fill.exec_mode,
      'kind': fill.kind,
      'subaccount': fill.subaccount,
    },
  )
