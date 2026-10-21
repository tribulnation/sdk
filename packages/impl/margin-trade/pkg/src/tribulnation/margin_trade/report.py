"""margin.trade snapshots of the perp and spot wallets, and history from fills, funding
and transfers.

Every read is by address and unsigned, so a configured `address` is enough.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import asyncio
from typing_extensions import Any, AsyncIterable, Collection
from typed_margin_trade.info.user_funding import UserFundingRecord
from typed_margin_trade.schemas import ClearinghouseState, Fill
from typed_margin_trade.info.spot_clearinghouse_state import SpotClearinghouseState
from typed_margin_trade.user.get_transfer_history import TransferHistoryItem
from tribulnation.sdk.reporting import (
  Bonus,
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  Funding,
  FutureTrade,
  HistoryRecord,
  InternalTransfer,
  Observation,
  Position,
  Report as SDKReport,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  UnknownObservation,
)
from .core import PERP_ASSET, Public

EARLIEST = datetime(2025, 1, 1, tzinfo=timezone.utc)
"""The default history start, before the venue's launch: `start_time` may not be 0."""
FAUCET_PREFIX = 'faucet:'
"""The `txHash` of a testnet faucet credit (`faucet:<address>:<ms>`)."""


def perp_state(state: ClearinghouseState) -> SubaccountSnapshot:
  """The perp wallet's USDC and positions, without unrealized PnL.

  `accountValue` (and the venue's own `perpBalance`) include each position's
  `unrealizedPnl`, which is taken off to leave the cash balance.
  """
  unrealized = sum(
    (p['position']['unrealizedPnl'] for p in state['assetPositions']), Decimal(0)
  )
  balance = state['marginSummary']['accountValue'] - unrealized
  return SubaccountSnapshot(
    subaccount='perp',
    balances={PERP_ASSET: balance} if balance else {},
    positions={
      p['position']['coin']: Position(
        size=p['position']['szi'], avg_price=p['position']['entryPx']
      )
      for p in state['assetPositions']
    },
  )


def spot_state(state: SpotClearinghouseState) -> SubaccountSnapshot:
  """Spot token totals by name, held parts included."""
  return SubaccountSnapshot(
    subaccount='spot',
    balances={b['coin']: b['total'] for b in state['balances'] if b['total']},
  )


def fill_observation(fill: Fill) -> Observation:
  """A perp fill as `FutureTrade`, a spot fill (coin `<base>/<quote>`) as `SpotTrade`.

  `closedPnl` is net of the fill's fee (an opening fill's equals `-fee`), so the
  fee-exclusive realized PnL is `closedPnl + fee`.
  """
  side = 1 if fill['side'] == 'B' else -1
  common: dict[str, Any] = {
    'id': f'fill:{fill["tid"]}',
    'time': fill['time'],
    'order_id': str(fill['oid']),
    'fee': Fee(amount=fill['fee'], asset=fill['feeToken']),
    'price': fill['px'],
    'size': side * fill['sz'],
  }
  if '/' in fill['coin']:
    base, quote = fill['coin'].split('/', 1)
    return SpotTrade(
      **common, subaccount='spot', pair=fill['coin'], base=base, quote=quote
    )
  else:
    return FutureTrade(
      **common,
      subaccount='perp',
      instrument=fill['coin'],
      settle=PERP_ASSET,
      realized_pnl=fill['closedPnl'] + fill['fee'],
    )


def funding_observation(row: UserFundingRecord) -> Funding:
  """One settlement, received-positive."""
  delta = row['delta']
  return Funding(
    id=f'funding:{row["hash"]}',
    time=row['time'],
    subaccount='perp',
    asset=PERP_ASSET,
    amount=delta['usdc'],
    instrument=delta['coin'],
  )


def transfer_id(row: TransferHistoryItem) -> str:
  """Kind, credited wallet and creation time: a withdrawal and the perp-to-spot transfer
  feeding it share the time, not the kind."""
  ms = int(row['createdTime'].timestamp() * 1000)
  return f'transfer:{row["type"]}:{row["venue"]}:{ms}'


def transfer_observation(row: TransferHistoryItem) -> Observation:
  """
  One `getTransferHistory` row.

  A perp/spot transfer is a single row naming the credited wallet (`venue`). A
  withdrawal's `amountChange` is the whole debit, its fee included. `system` and
  `liquidation` rows stay unclassified.
  """
  common: dict[str, Any] = {
    'id': transfer_id(row),
    'time': row['createdTime'],
    'subaccount': row['venue'],
    'asset': row['asset'],
  }
  tx = row.get('txHash')
  chain: dict[str, Any] = {
    'network': row.get('chain'),
    'tx_id': tx,
    'src_address': row['from'] or None,
    'dst_address': row['to'] or None,
  }
  match row['type']:
    case 'deposit' if tx is not None and tx.startswith(FAUCET_PREFIX):
      return Bonus(**common, amount=row['amountChange'], category='faucet')
    case 'deposit':
      return CryptoDeposit(**common, **chain, amount=row['amountChange'])
    case 'withdrawal':
      fee = Fee(amount=row['fee'], asset=row['asset']) if row['fee'] else None
      return CryptoWithdrawal(**common, **chain, amount=row['amountChange'], fee=fee)
    case 'transfer':
      source = 'spot' if row['venue'] == 'perp' else 'perp'
      return InternalTransfer(
        **common, amount=row['amount'], src_account=source, dst_account=row['venue']
      )
    case _:
      return UnknownObservation(**common, amount=row['amountChange'])


@dataclass(frozen=True, kw_only=True)
class Report(Public, SDKReport):
  """Perp and spot wallet snapshots, and the account's fills, funding and transfers."""

  def record(
    self, observation: Observation, *, id: str, details: object
  ) -> HistoryRecord:
    """Wrap one observation with its API provenance."""
    return HistoryRecord(
      observations=[observation],
      provenance={
        'source': 'api',
        'service': self.venue_id,
        'id': id,
        'details': details,
      },
    )

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """The `perp` wallet (USDC and positions) and the `spot` wallet.

    Args:
      assets: Ignored: the venue enumerates holdings.
    """
    address = self.shared.address
    state, spot = await asyncio.gather(
      self.shared.call(lambda: self.client.info.clearinghouse_state(user=address)),
      self.shared.call(lambda: self.client.info.spot_clearinghouse_state(address)),
    )
    snapshot = Snapshot(subaccounts=[perp_state(state), spot_state(spot)])
    return SnapshotRecord(
      snapshot=snapshot,
      provenance={
        'source': 'api',
        'service': self.venue_id,
        'id': snapshot.time.isoformat(),
      },
    )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """
    Stream fills (newest first, paged), then funding, then transfers.

    `userFillsByTime` retains the 10000 most recent fills; transfers come whole in one
    response and are filtered to the window here.

    Args:
      start: Inclusive lower bound; defaults to before the venue's launch.
      end: Inclusive upper bound; defaults to now.
    """
    upper = end or datetime.now(timezone.utc)
    lower = start or EARLIEST
    if lower.tzinfo is None or upper.tzinfo is None:
      raise ValueError('History bounds must be timezone-aware')
    if upper < lower:
      raise ValueError('History end precedes start')
    address = self.shared.address
    fills = self.client.info.user_fills_by_time_paged(
      address, start_time=lower, end_time=upper
    )
    async for page in fills.via(self.shared.call):
      for fill in page:
        yield self.record(
          fill_observation(fill), id=f'fill:{fill["tid"]}', details=fill
        )
    funding = await self.shared.call(
      lambda: self.client.info.user_funding(address, start_time=lower, end_time=upper)
    )
    for row in funding:
      yield self.record(
        funding_observation(row), id=f'funding:{row["hash"]}', details=row
      )
    transfers = await self.shared.call(
      lambda: self.client.user.get_transfer_history(address)
    )
    for row in transfers['items']:
      if lower <= row['createdTime'] <= upper:
        yield self.record(transfer_observation(row), id=transfer_id(row), details=row)
