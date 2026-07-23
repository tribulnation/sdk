from typing_extensions import Iterable, Callable, Awaitable, TypeVar, Protocol
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import CosmosTx, Record, source_id
from tribulnation.dydx.core import wrap_exceptions
from dydx import Dydx
from dydx.chain import Comet
from dydx.chain.comet.types import TxResponse, Event, EventAttribute
from .block_time import BlockTimeCache, MemoryBlockTimeCache

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
  actions = [e for e in event_group if e.type == 'message' and e.get('action') is not None]
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
  hash = tx['hash'] # type: ignore
  height = int(tx['height']) # type: ignore
  raw_events = tx['tx_result']['events'] # type: ignore
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
    tx_id=hash,
    height=height,
    time=time,
    tx_events=tx_events,
    messages=messages
  )


@dataclass(kw_only=True)
class ChainHistory(SDK):
  address: str
  comet: Comet
  chain_semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))
  block_time_cache: BlockTimeCache

  async def __aenter__(self):
    await self.comet.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.comet.__aexit__(exc_type, exc_value, traceback)

  @classmethod
  def of(cls, address: str, dydx: Dydx, block_time_cache: BlockTimeCache | None = None):
    if block_time_cache is None:
      block_time_cache = MemoryBlockTimeCache()
    return cls(address=address, comet=dydx.chain.comet, block_time_cache=block_time_cache)

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    async with self.chain_semaphore:
      return await fn()

  @SDK.method
  @wrap_exceptions
  async def block_time(self, height: int) -> datetime:
    if (time := self.block_time_cache.get(height)) is not None:
      return time
    else:
      block = await self.comet.block(height)
      time = block['block']['header']['time']
      self.block_time_cache.set(height, time)
      return time


  async def tx_search(self, query: str, *, per_page: int | None = None):
    paging = self.comet.tx_search_paged(query, per_page=per_page)
    state = paging.init
    while state is not None:
      page, state = await self.call(lambda: paging.next(state)) # type: ignore
      yield page

  async def latest_block(self) -> tuple[int, datetime]:
    """Return the latest available block height and timestamp."""
    block = await self.call(lambda: self.comet.block())
    header = block['block']['header']
    return int(header['height']), header['time']

  async def height_at_or_after(
    self, time: datetime, *, latest_height: int, latest_time: datetime,
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
    self, time: datetime, *, latest_height: int, latest_time: datetime,
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
    self, start: datetime | None, end: datetime | None,
  ) -> tuple[int | None, int | None] | None:
    """Resolve an inclusive datetime window to optional block bounds."""
    if start is not None and end is not None and start > end:
      return None
    if start is None and end is None:
      return None, None
    latest_height, latest_time = await self.latest_block()
    start_height = (
      await self.height_at_or_after(
        start, latest_height=latest_height, latest_time=latest_time,
      )
      if start is not None else None
    )
    end_height = (
      await self.height_at_or_before(
        end, latest_height=latest_height, latest_time=latest_time,
      )
      if end is not None else None
    )
    if start is not None and start_height is None:
      return None
    if end is not None and end_height is None:
      return None
    if (
      start_height is not None and end_height is not None
      and start_height > end_height
    ):
      return None
    return start_height, end_height

  def bounded_query(
    self, query: str, *, start_height: int | None, end_height: int | None,
  ) -> str:
    """Add optional block-height predicates to a Comet query."""
    clauses = [query]
    if start_height is not None:
      clauses.append(f'tx.height >= {start_height}')
    if end_height is not None:
      clauses.append(f'tx.height <= {end_height}')
    return ' AND '.join(clauses)

  async def coin_spent_transactions(
    self, *, start_height: int | None, end_height: int | None,
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
    self, *, start_height: int | None, end_height: int | None,
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
    self, *, start_height: int | None, end_height: int | None,
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
    self, *, start_height: int | None, end_height: int | None,
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

  async def fetch_transactions(
    self, start: datetime | None = None, end: datetime | None = None,
  ) -> dict[str, TxResponse]:
    """Fetch account transactions within an inclusive time window."""
    if (window := await self.height_window(start, end)) is None:
      return {}
    start_height, end_height = window
    spent_txs, received_txs, fee_payer_txs, settled_funding_txs = await asyncio.gather(
      self.coin_spent_transactions(
        start_height=start_height, end_height=end_height,
      ),
      self.coin_received_transactions(
        start_height=start_height, end_height=end_height,
      ),
      self.fee_payer_transactions(
        start_height=start_height, end_height=end_height,
      ),
      self.settled_funding_transactions(
        start_height=start_height, end_height=end_height,
      ),
    )
    return {
      tx['hash']: tx # type: ignore
      for tx in spent_txs + received_txs + fee_payer_txs + settled_funding_txs
    }
    

  async def history(
    self, start: datetime | None = None, end: datetime | None = None,
  ):
    id = source_id('chain')
    transactions = await self.fetch_transactions(start, end)

    async def parse_transaction(tx: TxResponse):
      height = int(tx['height']) # type: ignore
      time = await self.block_time(height)
      obs = parse_tx(tx, time=time)
      return Record(observations=[obs], provenance={'source': 'api', 'service': 'chain', 'id': id})

    return await asyncio.gather(*[parse_transaction(tx) for tx in transactions.values()])
