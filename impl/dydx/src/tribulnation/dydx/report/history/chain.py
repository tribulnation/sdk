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


  async def coin_spent_transactions(self):
    txs: list[TxResponse] = []
    async for page in self.tx_search(f"coin_spent.spender='{self.address}'", per_page=100):
      txs.extend(page)
    return txs


  async def coin_received_transactions(self):
    txs: list[TxResponse] = []
    async for page in self.tx_search(f"transfer.recipient='{self.address}'", per_page=100):
      txs.extend(page)
    return txs


  async def fee_payer_transactions(self):
    txs: list[TxResponse] = []
    async for page in self.tx_search(f"tx.fee_payer='{self.address}'", per_page=100):
      txs.extend(page)
    return txs


  async def settled_funding_transactions(self):
    txs: list[TxResponse] = []
    async for page in self.tx_search(f"settled_funding.subaccount='{self.address}'", per_page=100):
      txs.extend(page)
    return txs


  async def fetch_transactions(self) -> dict[str, TxResponse]:
    spent_txs, received_txs, fee_payer_txs, settled_funding_txs = await asyncio.gather(
      self.coin_spent_transactions(),
      self.coin_received_transactions(),
      self.fee_payer_transactions(),
      self.settled_funding_transactions(),
    )
    return {
      tx['hash']: tx # type: ignore
      for tx in spent_txs + received_txs + fee_payer_txs + settled_funding_txs
    }
    

  async def history(self):
    id = source_id('chain')
    transactions = await self.fetch_transactions()

    async def parse_transaction(tx: TxResponse):
      height = int(tx['height']) # type: ignore
      time = await self.block_time(height)
      obs = parse_tx(tx, time=time)
      return Record(observations=[obs], provenance={'source': 'api', 'service': 'chain', 'id': id})

    return await asyncio.gather(*[parse_transaction(tx) for tx in transactions.values()])