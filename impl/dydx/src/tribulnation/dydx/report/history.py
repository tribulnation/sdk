"""API-backed dYdX reporting history."""

import asyncio

from typing_extensions import AsyncIterable, Awaitable, Callable, TypeVar
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.core import SDK
from tribulnation.dydx.core import wrap_exceptions
from tribulnation.sdk.reporting import (
  ApiProvenance,
  CryptoTransaction,
  CryptoTransfer,
  Fee,
  FutureTrade,
  Funding,
  History as _History,
  InternalTransfer,
  Record,
  UnknownObservation,
)

from dydx import Dydx
from dydx.indexer.data.get_fills import Fill
from dydx.indexer.data.get_subaccounts import Subaccount
from dydx.indexer.data.get_transfers import Account, Transfer
from dydx.chain.comet.types import Event, TxResponse
from dydx.node import DYDX_MAINNET_USDC_DENOM

USDC = 'USDC'
COMET_BLOCK_CONCURRENCY = 8
COMET_TX_SEARCH_PER_PAGE = 100
COMET_FUNDING_SEARCH_PER_PAGE = 100
USDC_QUANTUMS = Decimal(1_000_000)
T = TypeVar('T')

def in_window(time: datetime, *, start: datetime | None, end: datetime | None) -> bool:
  """Return whether a timestamp is within an optional reporting window."""
  return (start is None or time >= start) and (end is None or time <= end)

def parse_time(value: datetime | str) -> datetime:
  """Parse an API timestamp into a datetime."""
  if isinstance(value, datetime):
    return value
  return datetime.fromisoformat(value.replace('Z', '+00:00'))

def account_label(account: Account) -> str:
  """Format a dYdX account and optional subaccount number."""
  subaccount = account.get('subaccountNumber')
  if subaccount is None:
    return account['address']
  return f'{account["address"]}:{subaccount}'

def is_account(account: Account, *, address: str, subaccount: int) -> bool:
  """Return whether an indexer account points at the requested subaccount."""
  return account['address'] == address and account.get('subaccountNumber') == subaccount

def instrument_assets(instrument: str) -> tuple[str | None, str | None]:
  """Split a dYdX instrument into base and quote assets when possible."""
  parts = instrument.split('-', 1)
  if len(parts) != 2:
    return None, None
  return parts[0], parts[1]

def fill_realized_pnl(fill: Fill) -> Decimal | None:
  """Compute realized PnL from dYdX fill position context."""
  size_before = fill.get('positionSizeBefore')
  entry_before = fill.get('entryPriceBefore')
  if size_before is None or entry_before is None:
    return None
  return position_realized_pnl(
    signed_before=Decimal(size_before),
    entry_before=Decimal(entry_before),
    signed_fill=fill_signed_size(fill),
    price=Decimal(fill['price']),
  )

def fill_signed_size(fill: Fill) -> Decimal:
  """Return the signed position change for a dYdX fill."""
  return Decimal(fill['size']) if fill['side'] == 'BUY' else -Decimal(fill['size'])

def position_realized_pnl(
  *, signed_before: Decimal, entry_before: Decimal | None, signed_fill: Decimal, price: Decimal,
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
  *, signed_before: Decimal, entry_before: Decimal | None, signed_fill: Decimal, price: Decimal,
) -> tuple[Decimal, Decimal | None]:
  """Update position size and entry price after a fill."""
  signed_after = signed_before + signed_fill
  if signed_after == 0:
    return Decimal(0), None
  if signed_before == 0 or signed_before * signed_fill < 0 and abs(signed_fill) > abs(signed_before):
    return signed_after, price
  if signed_before * signed_fill < 0:
    return signed_after, entry_before
  if entry_before is None:
    return signed_after, price
  notional = abs(signed_before) * entry_before + abs(signed_fill) * price
  return signed_after, notional / abs(signed_after)

def fill_sort_key(fill: Fill) -> tuple[datetime, int, str]:
  """Return a stable chronological sort key for fills."""
  return fill['createdAt'], int(fill['createdAtHeight']), fill['id']

def event_attributes(event: Event) -> dict[str, str]:
  """Return Comet event attributes by key."""
  return {
    attribute['key']: attribute['value']
    for attribute in event.get('attributes', [])
  }

def asset_symbol(denom: str) -> str:
  """Return the reporting asset symbol for a dYdX chain denom."""
  return USDC if denom == DYDX_MAINNET_USDC_DENOM else denom

def parse_coin(value: str) -> tuple[str, Decimal] | None:
  """Parse a single Cosmos coin amount into asset and decimal quantity."""
  for index, char in enumerate(value):
    if not char.isdigit():
      amount = Decimal(value[:index])
      denom = value[index:]
      return asset_symbol(denom), amount / USDC_QUANTUMS if denom == DYDX_MAINNET_USDC_DENOM else amount
  return None

class History(_History):
  """dYdX reporting history from the indexer plus Comet evidence."""

  address: str
  client: Dydx

  @property
  def indexer(self):
    """Return the indexer transport used for history reads."""
    return self.client.indexer

  @SDK.method
  @wrap_exceptions
  async def call_dydx(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call dYdX APIs and map typed-dydx exceptions into SDK exceptions."""
    return await fn()

  async def subaccounts(self) -> list[Subaccount]:
    """List dYdX subaccounts for the reporting address."""
    return (await self.indexer.data.get_subaccounts(self.address))['subaccounts']

  async def fills(self, subaccount: int, *, start: datetime | None, end: datetime | None) -> list[Fill]:
    """Fetch fills for a subaccount in the requested window."""
    paging = self.indexer.data.get_fills_paged(
      self.address,
      subaccount=subaccount,
      created_before_or_at=end,
      limit=1000,
    )
    state = paging.init
    rows: list[Fill] = []
    while state is not None:
      page, state = await self.call_dydx(lambda: paging.next(state)) # type: ignore
      for fill in page:
        if in_window(fill['createdAt'], start=start, end=end):
          rows.append(fill)
      if start is not None and page and page[-1]['createdAt'] < start:
        break
    return rows

  async def transfers(self, subaccount: int, *, start: datetime | None, end: datetime | None) -> list[Transfer]:
    """Fetch subaccount transfers in the requested window."""
    paging = self.indexer.data.get_transfers_paged(
      self.address,
      subaccount=subaccount,
      created_before_or_at=end,
      limit=1000,
    )
    state = paging.init
    rows: list[Transfer] = []
    while state is not None:
      page, state = await self.call_dydx(lambda: paging.next(state)) # type: ignore
      for transfer in page:
        if in_window(transfer['createdAt'], start=start, end=end):
          rows.append(transfer)
      if start is not None and page and page[-1]['createdAt'] < start:
        break
    return rows

  def parse_fill(self, fill: Fill, *, realized_pnl: Decimal | None = None) -> Record:
    """Convert an indexer fill into an SDK future trade record."""
    if realized_pnl is None:
      realized_pnl = fill_realized_pnl(fill)
    side = Decimal(1) if fill['side'] == 'BUY' else Decimal(-1)
    base, quote = instrument_assets(fill['market'])
    return Record(
      observations=[FutureTrade(
        id=fill['id'],
        time=fill['createdAt'],
        instrument=fill['market'],
        base=base,
        quote=quote,
        settle=USDC,
        side='buy' if fill['side'] == 'BUY' else 'sell',
        size=Decimal(fill['size']) * side,
        price=Decimal(fill['price']),
        realized_pnl=realized_pnl,
        subaccount=fill['subaccountNumber'],
        order_id=fill.get('orderId'),
        trade_id=fill['id'],
        fee=Fee(asset=USDC, amount=Decimal(fill['fee'])),
      )],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'fills', 'response': fill},
    )

  def parse_fills(
    self, fills: list[Fill], *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Convert a subaccount fill stream into future trade records."""
    positions: dict[str, tuple[Decimal, Decimal | None]] = {}
    records: list[Record] = []
    for fill in sorted(fills, key=fill_sort_key):
      signed_before, entry_before = positions.get(fill['market'], (Decimal(0), None))
      signed_fill = fill_signed_size(fill)
      price = Decimal(fill['price'])
      realized_pnl = fill_realized_pnl(fill)
      if realized_pnl is None:
        realized_pnl = position_realized_pnl(
          signed_before=signed_before,
          entry_before=entry_before,
          signed_fill=signed_fill,
          price=price,
        )
      positions[fill['market']] = update_position(
        signed_before=signed_before,
        entry_before=entry_before,
        signed_fill=signed_fill,
        price=price,
      )
      if in_window(fill['createdAt'], start=start, end=end):
        records.append(self.parse_fill(fill, realized_pnl=realized_pnl))
    return records

  def parse_transfer(self, transfer: Transfer, *, subaccount: int) -> Record | None:
    """Convert an indexer transfer into an SDK internal transfer record."""
    amount = Decimal(transfer['size'])
    if is_account(transfer['recipient'], address=self.address, subaccount=subaccount):
      signed = amount
    elif is_account(transfer['sender'], address=self.address, subaccount=subaccount):
      signed = -amount
    else:
      return None
    return Record(
      observations=[InternalTransfer(
        id=f"{transfer['id']}:{subaccount}",
        time=transfer['createdAt'],
        asset=transfer['symbol'],
        amount=signed,
        src_account=account_label(transfer['sender']),
        dst_account=account_label(transfer['recipient']),
      )],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'transfers', 'response': transfer},
    )

  async def subaccount_records(
    self, subaccount: int, *, start: datetime | None, end: datetime | None,
  ) -> tuple[list[Record], set[str]]:
    """Collect indexer evidence for one subaccount."""
    records: list[Record] = []
    seen_hashes: set[str] = set()
    fills, transfers = await asyncio.gather(
      self.fills(subaccount, start=None, end=end),
      self.transfers(subaccount, start=start, end=end),
    )
    records.extend(self.parse_fills(fills, start=start, end=end))
    for transfer in transfers:
      seen_hashes.add(transfer['transactionHash'])
      record = self.parse_transfer(transfer, subaccount=subaccount)
      if record is not None:
        records.append(record)
    return records, seen_hashes

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
      'endpoint': 'comet_tx_search',
      'response': {'tx': tx, 'event': event},
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
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'comet_tx_search', 'response': tx},
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
      coin = parse_coin(fee_value)
      if coin is None:
        continue
      asset, amount = coin
      return Fee(asset=asset, amount=amount)
    return None

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
        UnknownObservation(
          id=f'{tx_hash}:unknown',
          time=time,
          reason='dYdX inbound wallet transfer was not matched to an indexer transfer or supported semantic event.',
        ),
      ],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'comet_tx_search', 'response': tx},
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
      coin = parse_coin(amount)
      if coin is None:
        continue
      asset, change = coin
      transfers.append(CryptoTransfer(
        asset=asset,
        change=change,
        counterparty=attributes.get('sender'),
      ))
    return transfers

  async def chain_tx_time(self, tx: TxResponse, *, block_semaphore: asyncio.Semaphore | None = None) -> datetime | None:
    """Fetch the block timestamp for a Comet transaction."""
    height = tx.get('height')
    if height is None:
      return None
    async def block():
      """Fetch the Comet block for the transaction height."""
      return await self.call_dydx(lambda: self.client.chain.comet.block(int(height)))
    if block_semaphore is None:
      response = await block()
    else:
      async with block_semaphore:
        response = await block()
    return parse_time(response['block']['header']['time'])

  @wrap_exceptions
  async def history(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
    """Fetch dYdX account history records."""
    start = start.astimezone() if start is not None else None
    end = end.astimezone() if end is not None else None
    inbound_task = asyncio.create_task(self.fetch_comet_txs(
      f"transfer.recipient='{self.address}'",
      per_page=COMET_TX_SEARCH_PER_PAGE,
    ))
    fee_task = asyncio.create_task(self.fetch_comet_txs(
      f"tx.fee_payer='{self.address}'",
      per_page=COMET_TX_SEARCH_PER_PAGE,
    ))
    funding_task = asyncio.create_task(self.fetch_comet_txs(
      f"settled_funding.subaccount='{self.address}'",
      per_page=COMET_FUNDING_SEARCH_PER_PAGE,
    ))
    subaccounts = await self.subaccounts()
    records: list[Record] = []
    seen_hashes: set[str] = set()
    subaccount_results = await asyncio.gather(*[
      self.subaccount_records(subaccount['subaccountNumber'], start=start, end=end)
      for subaccount in subaccounts
    ])
    for subaccount_records, subaccount_hashes in subaccount_results:
      records.extend(subaccount_records)
      seen_hashes.update(subaccount_hashes)
    inbound_txs, fee_txs, funding_txs = await asyncio.gather(
      inbound_task,
      fee_task,
      funding_task,
    )
    funding_records, fee_records = await asyncio.gather(
      self.chain_funding(funding_txs, start=start, end=end),
      self.chain_fees(fee_txs, start=start, end=end),
    )
    inbound_records = await self.inbound_fallback(
      inbound_txs,
      covered_hashes=seen_hashes,
      fee_hashes=set(),
      start=start,
      end=end,
    )
    inbound_hashes = {
      observation.id
      for record in inbound_records
      for observation in record.observations
      if isinstance(observation, CryptoTransaction) and observation.id is not None
    }
    records.extend(funding_records)
    records.extend([
      record for record in fee_records
      if not any(
        isinstance(observation, CryptoTransaction) and observation.id in inbound_hashes
        for observation in record.observations
      )
    ])
    records.extend(inbound_records)
    for record in sorted(records, key=record_time):
      yield record

def record_time(record: Record) -> datetime:
  """Return a stable sort key for a reporting record."""
  times = [
    observation.time for observation in record.observations
    if observation.time is not None
  ]
  if record.snapshots:
    times.extend(snapshot.time for snapshot in record.snapshots)
  return min(times) if times else datetime.min.replace(tzinfo=timezone.utc)
