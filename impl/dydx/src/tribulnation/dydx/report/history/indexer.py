from typing_extensions import Callable, Awaitable, TypeVar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import FutureTrade, Fee, Funding, source_id, Record
from tribulnation.dydx.core import wrap_exceptions, USDC
from dydx import Indexer, Dydx
from dydx.indexer.data.get_fills import Fill
from .window import in_window

T = TypeVar('T')

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


def parse_fills(fills: list[Fill]):
  """Convert a subaccount fill stream into future trade records."""
  positions: dict[str, tuple[Decimal, Decimal | None]] = {}
  trades: list[FutureTrade] = []
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
    trades.append(parse_fill(fill, realized_pnl=realized_pnl))
  return trades


@dataclass
class IndexerHistory(SDK):
  address: str
  indexer: Indexer

  async def __aenter__(self):
    await self.indexer.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.indexer.__aexit__(exc_type, exc_value, traceback)

  @classmethod
  def of(cls, address: str, dydx: Dydx | None = None):
    indexer = dydx and dydx.indexer or Indexer()
    return cls(address=address, indexer=indexer)

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    return await fn()

  async def fetch_fills(
    self, *, subaccount: int, end: datetime | None = None,
  ):
    fills: list[Fill] = []
    paging = self.indexer.data.get_fills_paged(
      self.address,
      subaccount=subaccount,
      created_before_or_at=end,
    )
    state = paging.init
    while state is not None:
      page, state = await self.call(lambda: paging.next(state)) # type: ignore
      fills.extend(page)
    return fills

  async def fills(
    self, *, subaccount: int,
    start: datetime | None = None, end: datetime | None = None,
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
    paging = self.indexer.data.get_funding_payments_paged(self.address, subaccount=subaccount)
    state = paging.init
    while state is not None:
      page, state = await self.call(lambda: paging.next(state)) # type: ignore
      for f in page:
        indexer_fundings.append(Funding(
          time=f['createdAt'],
          instrument=f['ticker'],
          amount=f['payment'],
          asset='USDC'
        ))

    return sorted(indexer_fundings, key=lambda f: f.time or datetime.min)

  @SDK.method
  @wrap_exceptions
  async def history(
    self, start: datetime | None = None, end: datetime | None = None,
  ):
    id = source_id('indexer')
    subaccounts = (await self.indexer.data.get_subaccounts(self.address))['subaccounts']
    nested_observations = await asyncio.gather(*[
      self.fills(
        subaccount=s['subaccountNumber'],
        start=start,
        end=end,
      )
      for s in subaccounts
    ])
    return [
      Record(observations=[o], provenance={'source': 'api', 'service': 'indexer', 'id': id})
      for nested in nested_observations
      for o in nested
    ]
