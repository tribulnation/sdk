"""Comet-backed dYdX reporting history."""

from typing_extensions import Awaitable, Callable, Protocol, Sequence, TypeVar
import asyncio
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.reporting import (
  ApiProvenance,
  CryptoTransaction,
  CryptoTransfer,
  Fee,
  Funding,
  InternalTransfer,
  Record,
  Transfer,
  Yield,
  source_id,
)

from dydx import Dydx
from dydx.chain.comet.types import Event, TxResponse
from .accounts import megavault_account, staking_account, subaccount_account, wallet_account
from .coins import parse_coins, parse_fee_coin
from .constants import COMET_BLOCK_CONCURRENCY, COMET_TX_SEARCH_PER_PAGE, DYDX, USDC, USDC_QUANTUMS
from .time import in_window, parse_time

T = TypeVar('T')
COMET_BLOCK_TIME_CACHE: dict[str, datetime | None] = {}

class EventParser(Protocol):
  """Parser callback for one Comet event with transaction context."""
  def __call__(
    self,
    event: Event,
    *,
    tx: TxResponse,
    time: datetime | None,
    event_index: int,
  ) -> Record | None:
    """Parse one event into one SDK record."""

def event_attributes(event: Event) -> dict[str, str]:
  """Return Comet event attributes by key."""
  return {
    attribute['key']: attribute['value']
    for attribute in event.get('attributes', [])
  }

def usdc_from_quantums(value: str) -> Decimal:
  """Convert dYdX quote quantums into USDC units."""
  return Decimal(value) / USDC_QUANTUMS

class CometHistory:
  """Comet-backed dYdX history methods."""
  address: str
  client: Dydx
  comet_block_times: dict[str, datetime | None]
  comet_block_time_tasks: dict[str, asyncio.Task[datetime | None]]

  async def call_dydx(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call dYdX APIs and map typed-dydx exceptions into SDK exceptions."""
    return await fn()

  async def fetch_comet_txs(
    self, query: str, *, per_page: int = COMET_TX_SEARCH_PER_PAGE,
  ) -> list[TxResponse]:
    """Fetch and de-duplicate all Comet transactions matching a query."""
    paging = self.client.chain.comet.tx_search_paged(
      query,
      per_page=per_page,
      order_by='desc',
    )
    state = paging.init
    txs: list[TxResponse] = []
    seen: set[str] = set()
    while state is not None:
      page, state = await self.call_dydx(lambda: paging.next(state)) # type: ignore
      for tx in page:
        tx_hash = tx.get('hash')
        if tx_hash is None or tx_hash in seen:
          continue
        seen.add(tx_hash)
        txs.append(tx)
    return txs

  async def fetch_comet_txs_many(
    self, queries: Sequence[str], *, per_page: int = COMET_TX_SEARCH_PER_PAGE,
  ) -> list[TxResponse]:
    """Fetch and de-duplicate transactions matching any Comet query."""
    pages = await asyncio.gather(*[
      self.fetch_comet_txs(query, per_page=per_page)
      for query in queries
    ])
    txs: list[TxResponse] = []
    seen: set[str] = set()
    for page in pages:
      for tx in page:
        tx_hash = tx.get('hash')
        if tx_hash is None or tx_hash in seen:
          continue
        seen.add(tx_hash)
        txs.append(tx)
    return txs

  async def chain_funding(
    self, txs: list[TxResponse], *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect canonical settled funding events from fetched Comet evidence."""
    block_semaphore = asyncio.Semaphore(COMET_BLOCK_CONCURRENCY)
    parsed = await asyncio.gather(*[
      self.parse_funding_tx(tx, start=start, end=end, block_semaphore=block_semaphore)
      for tx in txs
    ])
    records: list[Record] = []
    for tx_records in parsed:
      records.extend(tx_records)
    return records

  async def parse_funding_tx(
    self,
    tx: TxResponse,
    *,
    start: datetime | None,
    end: datetime | None,
    block_semaphore: asyncio.Semaphore | None = None,
  ) -> list[Record]:
    """Convert settled funding events in one Comet transaction."""
    time = await self.chain_tx_time(tx, block_semaphore=block_semaphore)
    if time is not None and not in_window(time, start=start, end=end):
      return []
    records: list[Record] = []
    for event_index, event in enumerate(tx.get('tx_result', {}).get('events', [])):
      record = self.parse_settled_funding_event(event, tx=tx, time=time, event_index=event_index)
      if record is not None:
        records.append(record)
    return records

  def parse_settled_funding_event(
    self, event: Event, *, tx: TxResponse, time: datetime | None, event_index: int,
  ) -> Record | None:
    """Convert one Comet settled funding event into an SDK funding record."""
    if event['type'] != 'settled_funding':
      return None
    attributes = event_attributes(event)
    if attributes.get('subaccount') != self.address:
      return None
    amount = -Decimal(attributes['funding_paid_quote_quantums']) / USDC_QUANTUMS
    tx_hash = tx.get('hash')
    provenance: ApiProvenance = {
      'source': 'api',
      'service': 'dydx',
      'id': source_id('dydx'),
    }
    return Record(
      observations=[Funding(
        id=f'{tx_hash}:{event_index}',
        time=time,
        asset=USDC,
        amount=amount,
      )],
      provenance=provenance,
    )

  async def chain_fees(
    self, txs: list[TxResponse], *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect wallet-paid Comet chain fees from fetched transactions."""
    block_semaphore = asyncio.Semaphore(COMET_BLOCK_CONCURRENCY)
    parsed = await asyncio.gather(*[
      self.parse_chain_fee_tx(tx, start=start, end=end, block_semaphore=block_semaphore)
      for tx in txs
    ])
    records: list[Record] = []
    for record in parsed:
      if record is not None:
        records.append(record)
    return records

  async def parse_chain_fee_tx(
    self,
    tx: TxResponse,
    *,
    start: datetime | None,
    end: datetime | None,
    block_semaphore: asyncio.Semaphore | None = None,
  ) -> Record | None:
    """Convert one wallet-paid Comet tx fee into a crypto transaction record."""
    fee = self.chain_fee(tx)
    if fee is None:
      return None
    time = await self.chain_tx_time(tx, block_semaphore=block_semaphore)
    if time is not None and not in_window(time, start=start, end=end):
      return None
    tx_hash = tx.get('hash')
    return Record(
      observations=[CryptoTransaction(id=tx_hash, time=time, tx_id=tx_hash, fee=fee)],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  def chain_fee(self, tx: TxResponse) -> Fee | None:
    """Return the wallet-paid chain fee from Comet tx events."""
    for event in tx.get('tx_result', {}).get('events', []):
      if event['type'] != 'tx':
        continue
      attributes = event_attributes(event)
      if attributes.get('fee_payer') != self.address:
        continue
      fee_value = attributes.get('fee')
      if fee_value is None:
        continue
      asset, amount = parse_fee_coin(fee_value)
      return Fee(asset=asset, amount=amount)
    return None

  async def chain_staking_transfers(
    self, txs: list[TxResponse], *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect staking allocation movements from wallet-paid Comet transactions."""
    block_semaphore = asyncio.Semaphore(COMET_BLOCK_CONCURRENCY)
    parsed = await asyncio.gather(*[
      self.parse_staking_tx(tx, start=start, end=end, block_semaphore=block_semaphore)
      for tx in txs
    ])
    records: list[Record] = []
    for tx_records in parsed:
      records.extend(tx_records)
    return records

  async def parse_staking_tx(
    self,
    tx: TxResponse,
    *,
    start: datetime | None,
    end: datetime | None,
    block_semaphore: asyncio.Semaphore | None = None,
  ) -> list[Record]:
    """Convert dYdX delegate and unbond events into internal transfers."""
    time = await self.chain_tx_time(tx, block_semaphore=block_semaphore)
    if time is not None and not in_window(time, start=start, end=end):
      return []
    records: list[Record] = []
    for event_index, event in enumerate(tx.get('tx_result', {}).get('events', [])):
      record = self.parse_staking_event(event, tx=tx, time=time, event_index=event_index)
      if record is not None:
        records.append(record)
    return records

  def parse_staking_event(
    self, event: Event, *, tx: TxResponse, time: datetime | None, event_index: int,
  ) -> Record | None:
    """Convert one Comet staking event into an internal transfer record."""
    if event['type'] == 'withdraw_rewards':
      return self.parse_withdraw_rewards_event(event, tx=tx, time=time, event_index=event_index)
    if event['type'] not in {'delegate', 'unbond'}:
      return None
    attributes = event_attributes(event)
    if attributes.get('delegator') != self.address:
      return None
    amount_value = attributes.get('amount')
    if amount_value is None:
      return None
    asset, amount = parse_fee_coin(amount_value)
    if asset != DYDX:
      return None
    tx_hash = tx.get('hash')
    if tx_hash is None:
      return None
    validator = attributes.get('validator')
    if event['type'] == 'delegate':
      src_account = wallet_account(self.address)
      dst_account = staking_account(self.address, validator=validator)
    else:
      src_account = staking_account(self.address, validator=validator)
      dst_account = wallet_account(self.address)
    return Record(
      observations=[InternalTransfer(
        id=f'{tx_hash}:{event["type"]}:{event_index}',
        time=time,
        asset=DYDX,
        amount=amount,
        src_account=src_account,
        dst_account=dst_account,
      )],
      provenance={
        'source': 'api',
        'service': 'dydx',
        'id': source_id('dydx'),
      },
    )

  def parse_withdraw_rewards_event(
    self, event: Event, *, tx: TxResponse, time: datetime | None, event_index: int,
  ) -> Record | None:
    """Convert one staking reward withdrawal event into yield records."""
    attributes = event_attributes(event)
    if attributes.get('delegator') != self.address:
      return None
    amount_value = attributes.get('amount')
    if amount_value is None:
      return None
    observations: list[Yield] = []
    tx_hash = tx.get('hash')
    for coin_index, (asset, amount) in enumerate(parse_coins(amount_value)):
      if amount == 0:
        continue
      observations.append(Yield(
        id=f'{tx_hash}:withdraw_rewards:{event_index}:{coin_index}',
        time=time,
        asset=asset,
        amount=amount,
      ))
    if not observations:
      return None
    return Record(
      observations=observations,
      provenance={
        'source': 'api',
        'service': 'dydx',
        'id': source_id('dydx'),
      },
    )

  async def chain_subaccount_transfers(
    self, txs: list[TxResponse], *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect subaccount transfers from signed wallet Comet transactions."""
    return await self.parse_event_records(txs, self.parse_subaccount_transfer_event, start=start, end=end)

  def parse_subaccount_transfer_event(
    self, event: Event, *, tx: TxResponse, time: datetime | None, event_index: int,
  ) -> Record | None:
    """Convert one dYdX subaccount movement event into an internal transfer."""
    attributes = event_attributes(event)
    tx_hash = tx.get('hash')
    if event['type'] == 'deposit_to_subaccount':
      if attributes.get('sender') != self.address and attributes.get('recipient') != self.address:
        return None
      amount = self.parse_subaccount_quantums(attributes)
      if amount is None:
        return None
      sender = attributes.get('sender', self.address)
      recipient = attributes.get('recipient')
      recipient_number = attributes.get('recipient_number')
      src_account = wallet_account(sender)
      dst_account = subaccount_account(recipient or self.address, recipient_number)
    elif event['type'] == 'withdraw_from_subaccount':
      if attributes.get('sender') != self.address and attributes.get('recipient') != self.address:
        return None
      amount = self.parse_subaccount_quantums(attributes)
      if amount is None:
        return None
      sender = attributes.get('sender')
      sender_number = attributes.get('sender_number')
      recipient = attributes.get('recipient', self.address)
      src_account = subaccount_account(sender or self.address, sender_number)
      dst_account = wallet_account(recipient)
    elif event['type'] == 'create_transfer':
      if attributes.get('sender') != self.address and attributes.get('recipient') != self.address:
        return None
      amount = self.parse_subaccount_quantums(attributes)
      if amount is None:
        return None
      sender = attributes.get('sender')
      sender_number = attributes.get('sender_number')
      recipient = attributes.get('recipient')
      recipient_number = attributes.get('recipient_number')
      src_account = subaccount_account(sender or self.address, sender_number)
      dst_account = subaccount_account(recipient or self.address, recipient_number)
    else:
      return None
    return Record(
      observations=[InternalTransfer(
        id=f'{tx_hash}:{event["type"]}:{event_index}',
        time=time,
        asset=USDC,
        amount=amount,
        src_account=src_account,
        dst_account=dst_account,
      )],
      provenance={
        'source': 'api',
        'service': 'dydx',
        'id': source_id('dydx'),
      },
    )

  def parse_subaccount_quantums(self, attributes: dict[str, str]) -> Decimal | None:
    """Return USDC amount for dYdX subaccount events."""
    if attributes.get('asset_id') not in {None, '0'}:
      return None
    quantums = attributes.get('quantums')
    if quantums is None:
      return None
    return usdc_from_quantums(quantums)

  async def chain_megavault_transfers(
    self, txs: list[TxResponse], *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect Megavault deposits and withdrawals from Comet transactions."""
    return await self.parse_event_records(txs, self.parse_megavault_event, start=start, end=end)

  def parse_megavault_event(
    self, event: Event, *, tx: TxResponse, time: datetime | None, event_index: int,
  ) -> Record | None:
    """Convert one dYdX Megavault event into an internal transfer."""
    attributes = event_attributes(event)
    tx_hash = tx.get('hash')
    if event['type'] == 'deposit_to_megavault':
      if attributes.get('depositor') != self.address:
        return None
      quantums = attributes.get('quote_quantums')
      if quantums is None:
        return None
      src_account = subaccount_account(self.address, 0)
      dst_account = megavault_account(self.address)
      amount = -usdc_from_quantums(quantums)
    elif event['type'] == 'withdraw_from_megavault':
      if attributes.get('withdrawer') != self.address:
        return None
      quantums = attributes.get('redeemed_quote_quantums')
      if quantums is None:
        return None
      src_account = megavault_account(self.address)
      dst_account = subaccount_account(self.address, 0)
      amount = usdc_from_quantums(quantums)
    else:
      return None
    return Record(
      observations=[Transfer(
        id=f'{tx_hash}:{event["type"]}:{event_index}',
        time=time,
        asset=USDC,
        amount=amount,
        src_account=src_account,
        dst_account=dst_account,
      )],
      provenance={
        'source': 'api',
        'service': 'dydx',
        'id': source_id('dydx'),
      },
    )

  async def chain_ibc_transfers(
    self, txs: list[TxResponse], *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect IBC wallet transfers from Comet transactions."""
    return await self.parse_event_records(txs, self.parse_ibc_transfer_event, start=start, end=end)

  def parse_ibc_transfer_event(
    self, event: Event, *, tx: TxResponse, time: datetime | None, event_index: int,
  ) -> Record | None:
    """Convert one IBC movement event into an account transfer."""
    attributes = event_attributes(event)
    if event['type'] == 'ibc_transfer':
      if attributes.get('sender') != self.address:
        return None
      denom = attributes.get('denom')
      amount = attributes.get('amount')
      if denom is None or amount is None:
        return None
      asset, quantity = parse_fee_coin(f'{amount}{denom}')
      signed = -quantity
      src_account = self.address
      dst_account = attributes.get('receiver')
    elif event['type'] == 'fungible_token_packet':
      if attributes.get('receiver') != self.address or attributes.get('success') == 'false':
        return None
      denom = attributes.get('denom')
      amount = attributes.get('amount')
      if denom is None or amount is None:
        return None
      asset, signed = parse_fee_coin(f'{amount}{denom}')
      src_account = attributes.get('sender')
      dst_account = self.address
    else:
      return None
    tx_hash = tx.get('hash')
    return Record(
      observations=[Transfer(
        id=f'{tx_hash}:{event["type"]}:{event_index}',
        time=time,
        asset=asset,
        amount=signed,
        src_account=src_account,
        dst_account=dst_account,
      )],
      provenance={
        'source': 'api',
        'service': 'dydx',
        'id': source_id('dydx'),
      },
    )

  async def parse_event_records(
    self,
    txs: list[TxResponse],
    parser: EventParser,
    *,
    start: datetime | None,
    end: datetime | None,
  ) -> list[Record]:
    """Collect event-derived records from Comet transactions."""
    block_semaphore = asyncio.Semaphore(COMET_BLOCK_CONCURRENCY)
    parsed = await asyncio.gather(*[
      self.parse_events_tx(tx, parser, start=start, end=end, block_semaphore=block_semaphore)
      for tx in txs
    ])
    records: list[Record] = []
    for tx_records in parsed:
      records.extend(tx_records)
    return records

  async def parse_events_tx(
    self,
    tx: TxResponse,
    parser: EventParser,
    *,
    start: datetime | None,
    end: datetime | None,
    block_semaphore: asyncio.Semaphore | None = None,
  ) -> list[Record]:
    """Convert matching events in one transaction using a parser callback."""
    time = await self.chain_tx_time(tx, block_semaphore=block_semaphore)
    if time is not None and not in_window(time, start=start, end=end):
      return []
    records: list[Record] = []
    for event_index, event in enumerate(tx.get('tx_result', {}).get('events', [])):
      record = parser(event, tx=tx, time=time, event_index=event_index)
      if record is not None:
        records.append(record)
    return records

  async def inbound_fallback(
    self,
    txs: list[TxResponse],
    *,
    covered_hashes: set[str],
    fee_hashes: set[str],
    start: datetime | None,
    end: datetime | None,
  ) -> list[Record]:
    """Collect fallback wallet-credit evidence from inbound Comet transfers."""
    block_semaphore = asyncio.Semaphore(COMET_BLOCK_CONCURRENCY)
    parsed = await asyncio.gather(*[
      self.parse_inbound_fallback_tx(
        tx,
        covered_hashes=covered_hashes,
        include_fee=tx.get('hash') not in fee_hashes,
        start=start,
        end=end,
        block_semaphore=block_semaphore,
      )
      for tx in txs
    ])
    records: list[Record] = []
    for record in parsed:
      if record is not None:
        records.append(record)
    return records

  async def parse_inbound_fallback_tx(
    self,
    tx: TxResponse,
    *,
    covered_hashes: set[str],
    include_fee: bool,
    start: datetime | None,
    end: datetime | None,
    block_semaphore: asyncio.Semaphore | None = None,
  ) -> Record | None:
    """Convert unmatched inbound wallet transfers into fallback chain evidence."""
    tx_hash = tx.get('hash')
    if tx_hash is None or tx_hash in covered_hashes:
      return None
    transfers = self.inbound_transfers(tx)
    fee = self.chain_fee(tx) if include_fee else None
    if not transfers and fee is None:
      return None
    time = await self.chain_tx_time(tx, block_semaphore=block_semaphore) if start is not None or end is not None else None
    if time is not None and not in_window(time, start=start, end=end):
      return None
    return Record(
      observations=[
        CryptoTransaction(id=tx_hash, time=time, tx_id=tx_hash, fee=fee, transfers=transfers),
      ],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  def inbound_transfers(self, tx: TxResponse) -> list[CryptoTransfer]:
    """Return wallet-credit transfer legs from generic Comet transfer events."""
    transfers: list[CryptoTransfer] = []
    for event in tx.get('tx_result', {}).get('events', []):
      if event['type'] != 'transfer':
        continue
      attributes = event_attributes(event)
      if attributes.get('recipient') != self.address:
        continue
      amount = attributes.get('amount')
      if amount is None:
        continue
      for asset, change in parse_coins(amount):
        transfers.append(CryptoTransfer(
          asset=asset,
          change=change,
          counterparty=attributes['sender'],
        ))
    return transfers

  async def chain_tx_time(self, tx: TxResponse, *, block_semaphore: asyncio.Semaphore | None = None) -> datetime | None:
    """Fetch the block timestamp for a Comet transaction."""
    height = tx.get('height')
    if height is None:
      return None
    cached = self.comet_block_times.get(height)
    if cached is not None:
      return cached
    if height in self.comet_block_times:
      return None
    cached = COMET_BLOCK_TIME_CACHE.get(height)
    if cached is not None:
      self.comet_block_times[height] = cached
      return cached
    if height in COMET_BLOCK_TIME_CACHE:
      self.comet_block_times[height] = None
      return None
    task = self.comet_block_time_tasks.get(height)
    if task is None:
      task = asyncio.create_task(self.fetch_chain_block_time(height, block_semaphore=block_semaphore))
      self.comet_block_time_tasks[height] = task
    try:
      time = await task
    finally:
      if task.done():
        self.comet_block_time_tasks.pop(height, None)
    self.comet_block_times[height] = time
    COMET_BLOCK_TIME_CACHE[height] = time
    return time

  async def fetch_chain_block_time(
    self, height: str, *, block_semaphore: asyncio.Semaphore | None = None,
  ) -> datetime | None:
    """Fetch and parse the Comet block timestamp for one height."""
    async def block():
      """Fetch the Comet block for the requested height."""
      return await self.call_dydx(lambda: self.client.chain.comet.block(int(height)))
    if block_semaphore is None:
      response = await block()
    else:
      async with block_semaphore:
        response = await block()
    return parse_time(response['block']['header']['time'])
