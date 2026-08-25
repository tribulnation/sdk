from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from tribulnation.dydx.core import wrap_exceptions
from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import CosmosTx, HistoryRecord, source_id
from typing_extensions import (
  AsyncContextManager,
  TypeVar,
)

from typed_dydx import Dydx
from typed_dydx.chain.comet import Comet
from typed_dydx.chain.comet.types import Event, EventAttribute, TxResponse

if TYPE_CHECKING:
  from .cache import HistoryCache

T = TypeVar('T')


def parse_attrs(attrs: Iterable[EventAttribute]):
  out = defaultdict[str, list[str]](list)
  for a in attrs:
    out[a['key']].append(a['value'])
  return CosmosTx.Event.Attrs(attrs=dict(out))


def parse_event(event: Event):
  attrs = parse_attrs(event['attributes'])
  if (idx := attrs.get('msg_index')) is not None:
    idx = int(idx)
  return CosmosTx.Event(
    type=event['type'],
    idx=idx,
    attrs=attrs,
  )


def parse_message(idx: int, event_group: list[CosmosTx.Event]):
  actions = [
    e for e in event_group if e.type == 'message' and e.get('action') is not None
  ]
  if not actions:
    raise ValueError('No message action')
  if len(actions) > 1:
    raise ValueError('Multiple message actions')
  action = actions[0]
  return CosmosTx.Message(
    idx=idx,
    action=action.get('action'),
    sender=action.get('sender'),
    module=action.get('module'),
    events=event_group,
  )


def parse_tx(tx: TxResponse, *, time: datetime):
  hash = tx['hash']  # type: ignore
  height = int(tx['height'])  # type: ignore
  raw_events = tx['tx_result']['events']  # type: ignore
  events = [parse_event(e) for e in raw_events]
  tx_events: list[CosmosTx.Event] = []
  msg_events = defaultdict[int, list[CosmosTx.Event]](list)
  for e in events:
    if e.idx is None:
      tx_events.append(e)
    else:
      msg_events[e.idx].append(e)

  messages = [parse_message(idx, e) for idx, e in sorted(msg_events.items())]
  return CosmosTx(
    tx_id=hash, height=height, time=time, tx_events=tx_events, messages=messages
  )


@dataclass(kw_only=True)
class ChainHistory(SDK):
  address: str
  comet: Comet
  chain_semaphore: asyncio.Semaphore = field(
    default_factory=lambda: asyncio.Semaphore(4)
  )
  cache: HistoryCache | None = None
  _block_times: dict[int, datetime] = field(default_factory=dict)

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.comet

  @classmethod
  def of(cls, address: str, dydx: Dydx, cache: HistoryCache | None = None):
    return cls(address=address, comet=dydx.chain.comet, cache=cache)

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    async with self.chain_semaphore:
      return await fn()

  @SDK.method
  @wrap_exceptions
  async def block_time(self, height: int) -> datetime:
    if (time := self._block_times.get(height)) is not None:
      return time
    if self.cache is not None and (time := self.cache.get(height)) is not None:
      self._block_times[height] = time
      return time
    block = await self.comet.block(height)
    time = block['block']['header']['time']
    self._block_times[height] = time
    if self.cache is not None:
      self.cache.set(height, time)
    return time

  async def tx_search(self, query: str, *, per_page: int | None = None):
    paging = self.comet.tx_search_paged(query, per_page=per_page)
    state = paging.init
    while state is not None:
      page, state = await self.call(
        lambda current_state=state: paging.next(current_state)
      )  # type: ignore
      yield page

  async def latest_block(self) -> tuple[int, datetime]:
    """Return the latest available block height and timestamp."""
    block = await self.call(lambda: self.comet.block())
    header = block['block']['header']
    return int(header['height']), header['time']

  async def height_at_or_after(
    self,
    time: datetime,
    *,
    latest_height: int,
    latest_time: datetime,
  ) -> int | None:
    """Find the first block whose timestamp is at or after a timestamp."""
    if time > latest_time:
      return None
    low, high = 1, latest_height
    while low < high:
      middle = (low + high) // 2
      if await self.block_time(middle) < time:
        low = middle + 1
      else:
        high = middle
    return low

  async def height_at_or_before(
    self,
    time: datetime,
    *,
    latest_height: int,
    latest_time: datetime,
  ) -> int | None:
    """Find the last block whose timestamp is at or before a timestamp."""
    if time >= latest_time:
      return latest_height
    if await self.block_time(1) > time:
      return None
    low, high = 1, latest_height
    while low < high:
      middle = (low + high + 1) // 2
      if await self.block_time(middle) <= time:
        low = middle
      else:
        high = middle - 1
    return low

  async def height_window(
    self,
    start: datetime | None,
    end: datetime | None,
  ) -> tuple[int, int] | None:
    """Resolve an inclusive datetime window to concrete block bounds."""
    if start is not None and end is not None and start > end:
      return None
    latest_height, latest_time = await self.latest_block()
    start_height = (
      await self.height_at_or_after(
        start,
        latest_height=latest_height,
        latest_time=latest_time,
      )
      if start is not None
      else 1
    )
    end_height = (
      await self.height_at_or_before(
        end,
        latest_height=latest_height,
        latest_time=latest_time,
      )
      if end is not None
      else latest_height
    )
    if start_height is None or end_height is None:
      return None
    if start_height > end_height:
      return None
    return start_height, end_height

  def bounded_query(
    self,
    query: str,
    *,
    start_height: int | None,
    end_height: int | None,
  ) -> str:
    """Add optional block-height predicates to a Comet query."""
    clauses = [query]
    if start_height is not None:
      clauses.append(f'tx.height >= {start_height}')
    if end_height is not None:
      clauses.append(f'tx.height <= {end_height}')
    return ' AND '.join(clauses)

  async def coin_spent_transactions(
    self,
    *,
    start_height: int | None,
    end_height: int | None,
  ):
    txs: list[TxResponse] = []
    query = self.bounded_query(
      f"coin_spent.spender='{self.address}'",
      start_height=start_height,
      end_height=end_height,
    )
    async for page in self.tx_search(query, per_page=100):
      txs.extend(page)
    return txs

  async def coin_received_transactions(
    self,
    *,
    start_height: int | None,
    end_height: int | None,
  ):
    txs: list[TxResponse] = []
    query = self.bounded_query(
      f"transfer.recipient='{self.address}'",
      start_height=start_height,
      end_height=end_height,
    )
    async for page in self.tx_search(query, per_page=100):
      txs.extend(page)
    return txs

  async def fee_payer_transactions(
    self,
    *,
    start_height: int | None,
    end_height: int | None,
  ):
    txs: list[TxResponse] = []
    query = self.bounded_query(
      f"tx.fee_payer='{self.address}'",
      start_height=start_height,
      end_height=end_height,
    )
    async for page in self.tx_search(query, per_page=100):
      txs.extend(page)
    return txs

  async def settled_funding_transactions(
    self,
    *,
    start_height: int | None,
    end_height: int | None,
  ):
    txs: list[TxResponse] = []
    query = self.bounded_query(
      f"settled_funding.subaccount='{self.address}'",
      start_height=start_height,
      end_height=end_height,
    )
    async for page in self.tx_search(query, per_page=100):
      txs.extend(page)
    return txs

  async def _fetch_from_node(
    self,
    *,
    start_height: int | None,
    end_height: int | None,
  ) -> dict[str, TxResponse]:
    spent_txs, received_txs, fee_payer_txs, settled_funding_txs = await asyncio.gather(
      self.coin_spent_transactions(
        start_height=start_height,
        end_height=end_height,
      ),
      self.coin_received_transactions(
        start_height=start_height,
        end_height=end_height,
      ),
      self.fee_payer_transactions(
        start_height=start_height,
        end_height=end_height,
      ),
      self.settled_funding_transactions(
        start_height=start_height,
        end_height=end_height,
      ),
    )
    return {
      tx['hash']: tx  # type: ignore
      for tx in spent_txs + received_txs + fee_payer_txs + settled_funding_txs
    }

  async def fetch_transactions(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> dict[str, TxResponse]:
    """Fetch account transactions within an inclusive time window."""
    if (window := await self.height_window(start, end)) is None:
      return {}
    start_height, end_height = window

    if self.cache is None:
      return await self._fetch_from_node(
        start_height=start_height,
        end_height=end_height,
      )

    fetched: dict[str, TxResponse] = {}
    for gap_start, gap_end in self.cache.chain_gaps(
      self.address,
      start_height=start_height,
      end_height=end_height,
    ):
      gap_txs = await self._fetch_from_node(
        start_height=gap_start,
        end_height=gap_end,
      )
      self.cache.write_chain_txs(
        self.address,
        gap_txs,
        start_height=gap_start,
        end_height=gap_end,
      )
      fetched.update(gap_txs)

    cached = self.cache.read_chain_txs(
      self.address,
      start_height=start_height,
      end_height=end_height,
    )
    return {**cached, **fetched}

  async def history(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ):
    id = source_id('chain')
    transactions = await self.fetch_transactions(start, end)

    async def parse_transaction(tx: TxResponse):
      """Parse one cached transaction with its block time."""
      height = int(tx['height'])  # type: ignore
      time = await self.block_time(height)
      obs = parse_tx(tx, time=time)
      return HistoryRecord(
        observations=[obs],
        provenance={'source': 'api', 'service': 'chain', 'id': id},
      )

    return await asyncio.gather(
      *[parse_transaction(tx) for tx in transactions.values()]
    )
