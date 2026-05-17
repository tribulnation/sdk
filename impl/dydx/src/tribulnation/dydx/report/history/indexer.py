"""Indexer-backed dYdX reporting history."""

from typing_extensions import Awaitable, Callable, TypeVar
import asyncio
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.reporting import Fee, FutureTrade, InternalTransfer, Record

from dydx import Dydx
from dydx.indexer.data.get_fills import Fill
from dydx.indexer.data.get_subaccounts import Subaccount
from dydx.indexer.data.get_transfers import Transfer
from .accounts import account_label, is_account
from .constants import USDC
from .time import in_window

T = TypeVar('T')

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

class IndexerHistory:
  """Indexer-backed dYdX history methods."""
  address: str
  client: Dydx

  @property
  def indexer(self):
    """Return the indexer transport used for history reads."""
    return self.client.indexer

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
    """Convert an indexer transfer into an SDK transfer record."""
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
    self,
    subaccount: int,
    *,
    start: datetime | None,
    end: datetime | None,
    include_fills: bool,
    include_transfers: bool,
  ) -> tuple[list[Record], set[str]]:
    """Collect indexer evidence for one subaccount."""
    records: list[Record] = []
    seen_hashes: set[str] = set()
    fills_task = asyncio.create_task(self.fills(subaccount, start=None, end=end)) if include_fills else None
    transfers_task = asyncio.create_task(self.transfers(subaccount, start=start, end=end)) if include_transfers else None
    fills = await fills_task if fills_task is not None else []
    transfers = await transfers_task if transfers_task is not None else []
    if include_fills:
      records.extend(self.parse_fills(fills, start=start, end=end))
    for transfer in transfers:
      seen_hashes.add(transfer['transactionHash'])
      record = self.parse_transfer(transfer, subaccount=subaccount)
      if record is not None:
        records.append(record)
    return records, seen_hashes
