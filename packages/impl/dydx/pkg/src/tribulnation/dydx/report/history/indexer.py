import asyncio
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import TYPE_CHECKING, TypeVar

from tribulnation.dydx.core import USDC, wrap_exceptions
from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import (
  Fee,
  Funding,
  FutureTrade,
  HistoryRecord,
  source_id,
)

from typed_dydx import Dydx, Indexer
from typed_dydx.indexer.data.get_fills import Fill

from .window import in_window

if TYPE_CHECKING:
  from .cache import HistoryCache

T = TypeVar('T')


def fill_signed_size(fill: Fill) -> Decimal:
  """Return the signed position change for a dYdX fill."""
  return Decimal(fill['size']) if fill['side'] == 'BUY' else -Decimal(fill['size'])


@dataclass(frozen=True)
class ReplayPosition:
  """Running position state reconstructed with average-cost accounting."""

  signed_size: Decimal = Decimal(0)
  entry_price: Decimal | None = None


def position_realized_pnl(
  *,
  signed_before: Decimal,
  entry_before: Decimal | None,
  signed_fill: Decimal,
  price: Decimal,
) -> Decimal | None:
  """Compute realized PnL from prior position state and a signed fill."""
  if signed_before == 0:
    return Decimal(0)
  if entry_before is None:
    return None
  if signed_before * signed_fill >= 0:
    return Decimal(0)
  closed = min(abs(signed_before), abs(signed_fill))
  direction = Decimal(1) if signed_before > 0 else Decimal(-1)
  return closed * direction * (price - entry_before)


def update_position(
  *,
  position: ReplayPosition,
  signed_fill: Decimal,
  price: Decimal,
) -> ReplayPosition:
  """Apply a fill using average-cost position accounting."""
  signed_before = position.signed_size
  signed_after = signed_before + signed_fill
  if signed_after == 0:
    return ReplayPosition()
  if (
    signed_before == 0
    or signed_before * signed_fill < 0
    and abs(signed_fill) > abs(signed_before)
  ):
    return ReplayPosition(
      signed_size=signed_after,
      entry_price=price,
    )
  if signed_before * signed_fill < 0:
    return ReplayPosition(
      signed_size=signed_after,
      entry_price=position.entry_price,
    )
  if position.entry_price is None:
    entry_price = price
  else:
    notional = abs(signed_before) * position.entry_price + abs(signed_fill) * price
    entry_price = notional / abs(signed_after)
  return ReplayPosition(
    signed_size=signed_after,
    entry_price=entry_price,
  )


def parse_fill(fill: Fill, *, realized_pnl: Decimal | None = None):
  """Convert an indexer fill into an SDK future trade record."""
  side = Decimal(1) if fill['side'] == 'BUY' else Decimal(-1)
  base, _ = fill['market'].split('-')
  return FutureTrade(
    id=fill['id'],
    time=fill['createdAt'],
    instrument=fill['market'],
    base=base,
    quote=USDC,
    settle=USDC,
    size=Decimal(fill['size']) * side,
    price=Decimal(fill['price']),
    realized_pnl=realized_pnl,
    subaccount=str(fill['subaccountNumber']),
    order_id=fill.get('orderId'),
    fee=Fee(asset=USDC, amount=Decimal(fill['fee'])),
  )


def replay_fills(
  fills: list[Fill],
) -> tuple[list[FutureTrade], dict[str, ReplayPosition]]:
  """Replay chronological fills into trades and terminal average-cost positions."""
  positions: dict[str, ReplayPosition] = {}
  trades: list[FutureTrade] = []
  previous_time: datetime | None = None
  for fill in fills:
    if previous_time is not None and fill['createdAt'] < previous_time:
      raise ValueError('dYdX fills are not in chronological order')
    previous_time = fill['createdAt']
    position = positions.get(fill['market'], ReplayPosition())
    signed_fill = fill_signed_size(fill)
    price = Decimal(fill['price'])
    realized_pnl = position_realized_pnl(
      signed_before=position.signed_size,
      entry_before=position.entry_price,
      signed_fill=signed_fill,
      price=price,
    )
    positions[fill['market']] = update_position(
      position=position,
      signed_fill=signed_fill,
      price=price,
    )
    trades.append(parse_fill(fill, realized_pnl=realized_pnl))
  return trades, positions


def parse_fills(fills: list[Fill]):
  """Convert a chronological subaccount fill stream into future trades."""
  trades, _ = replay_fills(fills)
  return trades


@dataclass
class IndexerHistory(SDK):
  address: str
  indexer: Indexer
  cache: 'HistoryCache | None' = None

  def resources(self) -> Iterable[AbstractAsyncContextManager[object]]:
    yield self.indexer

  @classmethod
  def of(
    cls, address: str, dydx: Dydx | None = None, cache: 'HistoryCache | None' = None
  ):
    indexer = dydx and dydx.indexer or Indexer()
    return cls(address=address, indexer=indexer, cache=cache)

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    return await fn()

  async def _fetch_from_indexer(
    self,
    *,
    subaccount: int,
    end: datetime | None = None,
  ) -> list[Fill]:
    response_order: list[Fill] = []
    paging = self.indexer.data.get_fills_paged(
      self.address,
      subaccount=subaccount,
      created_before_or_at=end,
    )
    state = paging.init
    while state is not None:
      page, state = await self.call(
        lambda current_state=state: paging.next(current_state)
      )  # type: ignore
      response_order.extend(page)
    ids = [fill['id'] for fill in response_order]
    if len(ids) != len(set(ids)):
      raise ValueError('dYdX fill pagination returned duplicate IDs')
    ascending = all(
      previous['createdAt'] <= current['createdAt']
      for previous, current in pairwise(response_order)
    )
    if ascending:
      return response_order
    descending = all(
      previous['createdAt'] >= current['createdAt']
      for previous, current in pairwise(response_order)
    )
    if descending:
      return list(reversed(response_order))
    raise ValueError('dYdX fills have inconsistent chronological ordering')

  async def effective_end(self, end: datetime | None) -> datetime:
    """Clamp a requested end to the latest time indexed by dYdX."""
    indexed_through = (await self.call(self.indexer.data.get_height))['time']
    if end is None or end > indexed_through:
      return indexed_through
    return end

  async def fetch_fills(
    self,
    *,
    subaccount: int,
    end: datetime | None = None,
  ) -> list[Fill]:
    end = await self.effective_end(end)
    if self.cache is None:
      return await self._fetch_from_indexer(subaccount=subaccount, end=end)

    coverage = self.cache.indexer_fill_coverage(self.address, subaccount)
    if coverage is None or coverage < end:
      fills = await self._fetch_from_indexer(subaccount=subaccount, end=end)
      self.cache.replace_indexer_fills(
        self.address,
        subaccount,
        fills,
        through=end,
      )
    return self.cache.read_indexer_fills(
      self.address,
      subaccount,
      end=end,
    )

  async def fills(
    self,
    *,
    subaccount: int,
    start: datetime | None = None,
    end: datetime | None = None,
  ):
    fills = await self.fetch_fills(
      subaccount=subaccount,
      end=end,
    )
    return [
      trade
      for trade in parse_fills(fills)
      if in_window(trade.time, start=start, end=end)
    ]

  # HERE FOR COMPLETENESS, BUT WE PREFER TO USE THE CHAIN HISTORY TO GET FUNDINGS (THIS HAS ROUNDING ERRORS)
  async def fundings(self, *, subaccount: int):
    indexer_fundings: list[Funding] = []
    paging = self.indexer.data.get_funding_payments_paged(
      self.address, subaccount=subaccount
    )
    state = paging.init
    while state is not None:
      page, state = await self.call(lambda: paging.next(state))  # type: ignore
      for f in page:
        indexer_fundings.append(
          Funding(
            time=f['createdAt'],
            instrument=f['ticker'],
            amount=f['payment'],
            asset='USDC',
          )
        )

    return sorted(indexer_fundings, key=lambda f: f.time or datetime.min)

  @SDK.method
  @wrap_exceptions
  async def history(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ):
    id = source_id('indexer')
    subaccounts = (await self.indexer.data.get_subaccounts(self.address))['subaccounts']
    nested_observations = await asyncio.gather(
      *[
        self.fills(
          subaccount=s['subaccountNumber'],
          start=start,
          end=end,
        )
        for s in subaccounts
      ]
    )
    return [
      HistoryRecord(
        observations=[o], provenance={'source': 'api', 'service': 'indexer', 'id': id}
      )
      for nested in nested_observations
      for o in nested
    ]
