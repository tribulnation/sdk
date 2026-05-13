"""API-backed dYdX reporting history."""

from typing_extensions import AsyncIterable, Sequence, TypedDict
from datetime import datetime
from decimal import Decimal

from tribulnation.dydx.core import wrap_exceptions
from tribulnation.sdk.reporting import (
  Fee,
  FutureTrade,
  Funding,
  History as SdkHistory,
  InternalTransfer,
  Pnl,
  Record,
  UnknownObservation,
)

from dydx import Dydx
from dydx.indexer.data.get_fills import Fill
from dydx.indexer.data.get_funding_payments import FundingPayment
from dydx.indexer.data.get_subaccounts import Subaccount
from dydx.indexer.data.get_transfers import Account, Transfer
from dydx.chain.comet.types import TxResponse

USDC = 'USDC'

class HistoricalPnlTick(TypedDict):
  """Raw dYdX historical PnL tick."""
  blockHeight: str
  blockTime: datetime | str
  createdAt: datetime | str
  equity: Decimal | str
  totalPnl: Decimal | str
  netTransfers: Decimal | str

class HistoricalPnlResponse(TypedDict):
  """Raw dYdX historical PnL response."""
  historicalPnl: list[HistoricalPnlTick]

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

def tx_hash(hash: str) -> str:
  """Normalize a transaction hash for Comet lookup."""
  return hash if hash.startswith('0x') else f'0x{hash}'

class History(SdkHistory):
  """dYdX reporting history from the indexer plus Comet evidence."""

  address: str
  client: Dydx

  @property
  def indexer(self):
    """Return the indexer transport used for history reads."""
    return self.client.indexer

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
      page, state = await paging.next(state)
      for fill in page:
        if in_window(fill['createdAt'], start=start, end=end):
          rows.append(fill)
      if start is not None and page and page[-1]['createdAt'] < start:
        break
    return rows

  async def funding_payments(
    self, subaccount: int, *, start: datetime | None, end: datetime | None,
  ) -> list[FundingPayment]:
    """Fetch funding payments for a subaccount in the requested window."""
    paging = self.indexer.data.get_funding_payments_paged(
      self.address,
      subaccount=subaccount,
      after_or_at=start,
      limit=1000,
    )
    state = paging.init
    rows: list[FundingPayment] = []
    while state is not None:
      page, state = await paging.next(state)
      rows.extend([
        item for item in page
        if in_window(item['createdAt'], start=start, end=end)
      ])
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
      page, state = await paging.next(state)
      for transfer in page:
        if in_window(transfer['createdAt'], start=start, end=end):
          rows.append(transfer)
      if start is not None and page and page[-1]['createdAt'] < start:
        break
    return rows

  async def latest_historical_pnl_tick(
    self, subaccount: int, *, at: datetime | None,
  ) -> HistoricalPnlTick | None:
    """Fetch the latest cumulative PnL tick at or before a timestamp."""
    response: HistoricalPnlResponse = await self.indexer.data.get_historical_pnl( # type: ignore[assignment]
      self.address,
      subaccount=subaccount,
      created_before_or_at=at,
      limit=1,
      validate=False,
    )
    rows = response['historicalPnl']
    if not rows:
      return None
    return rows[0]

  async def historical_pnl_baseline(
    self, subaccount: int, *, start: datetime | None,
  ) -> Decimal:
    """Fetch the cumulative PnL immediately before the reporting window."""
    if start is None:
      return Decimal(0)
    tick = await self.latest_historical_pnl_tick(subaccount, at=start)
    if tick is None:
      return Decimal(0)
    return Decimal(str(tick['totalPnl']))

  def parse_fill(self, fill: Fill) -> Record:
    """Convert an indexer fill into an SDK future trade record."""
    side = Decimal(1) if fill['side'] == 'BUY' else Decimal(-1)
    return Record(
      observations=[FutureTrade(
        id=fill['id'],
        time=fill['createdAt'],
        market=fill['market'],
        side='buy' if fill['side'] == 'BUY' else 'sell',
        size=Decimal(fill['size']) * side,
        price=Decimal(fill['price']),
        collateral_asset=USDC,
        subaccount=fill['subaccountNumber'],
        order_id=fill.get('orderId'),
        trade_id=fill['id'],
        fee=Fee(asset=USDC, amount=Decimal(fill['fee'])),
      )],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'fills', 'response': fill},
    )

  def parse_pnl(self, tick: HistoricalPnlTick, *, amount: Decimal, subaccount: int) -> Record:
    """Convert a historical PnL delta into a derived SDK PnL record."""
    return Record(
      observations=[Pnl(
        id=f'{subaccount}:{tick["blockHeight"]}',
        time=parse_time(tick['createdAt']),
        asset=USDC,
        amount=amount,
        subaccount=subaccount,
        basis='historical_pnl.totalPnl',
      )],
      provenance={
        'source': 'derived',
        'method': 'dydx_historical_pnl_delta',
        'reason': 'dYdX subaccount collateral reconciles from signed transfers plus cumulative historical PnL.',
        'params': {'subaccount': subaccount, 'tick': tick},
      },
    )

  async def pnl_records(
    self, subaccount: int, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Derive a signed PnL flow record from cumulative historical PnL."""
    previous = await self.historical_pnl_baseline(subaccount, start=start)
    tick = await self.latest_historical_pnl_tick(subaccount, at=end)
    if tick is None:
      return []
    current = Decimal(str(tick['totalPnl']))
    delta = current - previous
    if not delta:
      return []
    return [self.parse_pnl(tick, amount=delta, subaccount=subaccount)]

  def parse_funding_payment(self, payment: FundingPayment) -> Record:
    """Convert an indexer funding payment into an SDK funding record."""
    return Record(
      observations=[Funding(
        id=f'{payment["ticker"]}:{payment["createdAtHeight"]}:{payment["subaccountNumber"]}',
        time=payment['createdAt'],
        asset=USDC,
        amount=Decimal(payment['payment']),
      )],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'funding_payments', 'response': payment},
    )

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
        id=transfer['id'],
        time=transfer['createdAt'],
        asset=transfer['symbol'],
        amount=signed,
        src_account=account_label(transfer['sender']),
        dst_account=account_label(transfer['recipient']),
      )],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'transfers', 'response': transfer},
    )

  async def chain_evidence(self, seen_hashes: set[str], *, start: datetime | None, end: datetime | None) -> list[Record]:
    """Collect chain transaction evidence not already represented by indexer transfers."""
    records: list[Record] = []
    queries = [
      f"transfer.sender='{self.address}'",
      f"transfer.recipient='{self.address}'",
    ]
    for query in queries:
      response = await self.client.chain.comet.tx_search(query, per_page=100, order_by='desc', validate=False)
      for tx in response['txs']:
        hash = tx.get('hash')
        if hash is None or hash in seen_hashes:
          continue
        record = await self.parse_chain_tx(tx, start=start, end=end)
        if record is not None:
          records.append(record)
    return records

  async def parse_chain_tx(
    self, tx: TxResponse, *, start: datetime | None, end: datetime | None,
  ) -> Record | None:
    """Convert unmatched Comet transaction evidence into an unknown record."""
    height = tx.get('height')
    time: datetime | None = None
    if height is not None:
      block = await self.client.chain.comet.block(int(height), validate=False)
      time = parse_time(block['block']['header']['time'])
      if not in_window(time, start=start, end=end):
        return None
    hash = tx.get('hash')
    return Record(
      observations=[UnknownObservation(
        id=hash,
        time=time,
        reason='dYdX chain transaction involving the account was not matched to an indexer subaccount transfer.',
      )],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'comet_tx_search', 'response': tx},
    )

  @wrap_exceptions
  async def history(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
    """Fetch dYdX account history records."""
    start = start.astimezone() if start is not None else None
    end = end.astimezone() if end is not None else None
    subaccounts = await self.subaccounts()
    records: list[Record] = []
    seen_hashes: set[str] = set()
    for subaccount in subaccounts:
      number = subaccount['subaccountNumber']
      fills = await self.fills(number, start=start, end=end)
      transfers = await self.transfers(number, start=start, end=end)
      records.extend(self.parse_fill(fill) for fill in fills)
      records.extend(await self.pnl_records(number, start=start, end=end))
      for transfer in transfers:
        seen_hashes.add(transfer['transactionHash'])
        record = self.parse_transfer(transfer, subaccount=number)
        if record is not None:
          records.append(record)
    records.extend(await self.chain_evidence(seen_hashes, start=start, end=end))
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
  return min(times) if times else datetime.min
