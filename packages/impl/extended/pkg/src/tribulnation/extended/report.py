"""Extended snapshots and history of the sub-account an API key belongs to.

One API key reads exactly one sub-account: its balances, positions and history. A
wallet's other sub-accounts each need their own key, and so their own account.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio

from typing_extensions import Any, AsyncIterable, Collection
from typed_extended.account.asset_operations import AssetOperation
from typed_extended.account.funding_history import FundingPayment
from typed_extended.account.positions_history import PositionHistory
from typed_extended.account.schemas import Position as PositionRow
from typed_extended.account.spot_balances import SpotBalance
from typed_extended.account.trades import AccountTrade
from typed_extended.core.networks import Network
from typed_extended.info.markets import Market as MarketRow
from tribulnation.sdk.reporting import (
  Bonus,
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  FeeLeg,
  Funding,
  FuturePositionSummary,
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
)

from .core import Shared
from .market.common import Public, funding_received

EARLIEST = datetime(2024, 1, 1, tzinfo=timezone.utc)
"""The default history start, before Extended's launch: `funding_history` needs one."""
WITHDRAWALS = frozenset({'WITHDRAWAL', 'FAST_WITHDRAWAL', 'SLOW_WITHDRAWAL'})
"""Operation types that move funds off the venue."""
INTEREST_UNOBSERVED = (
  'Extended interest payments are not supported yet: the sign of `paymentAmount` is '
  'documented, not observed'
)


def subaccount_snapshot(
  account_id: int, balances: list[SpotBalance], positions: list[PositionRow]
) -> SubaccountSnapshot:
  """The sub-account's holdings, collateral included, and open positions by market.

  The collateral row is the wallet balance (deposits, withdrawals and realised PnL),
  without unrealised PnL.
  """
  return SubaccountSnapshot(
    subaccount=str(account_id),
    balances={r['asset']: r['balance'] for r in balances if r['balance']},
    positions={
      p['market']: Position(
        size=p['size'] if p['side'] == 'LONG' else -p['size'], avg_price=p['openPrice']
      )
      for p in positions
    },
  )


def operation(row: AssetOperation, names: dict[int, str]) -> list[Observation]:
  """One asset operation as observations; none when it moved no funds.

  Completed transfers between the wallet's sub-accounts are `InternalTransfer`s between
  sub-account ids, as Hyperliquid reports its sub-account transfers: the venue reports
  them from the key's side (`accountId` is the key's sub-account) and the amount's sign
  gives the direction. Completed deposits are `CryptoDeposit`s, testnet claims
  `Bonus`es, and withdrawals that are not `REJECTED` `CryptoWithdrawal`s (the balance
  is debited when one is created).
  """
  me = str(row['accountId'])
  asset = names[row['asset']]
  common: dict[str, Any] = {
    'id': f'operation:{row["id"]}',
    'time': row['time'],
    'subaccount': me,
    'asset': asset,
  }
  fee = Fee(amount=row['fee'], asset=asset) if row['fee'] else None
  status = row['status']
  kind = row['type']
  if kind == 'TRANSFER' and status == 'COMPLETED':
    peer = row.get('counterpartyAccountId')
    there = str(peer) if peer is not None else None
    out = row['amount'] < 0
    moved: list[Observation] = [
      InternalTransfer(
        **common,
        amount=abs(row['amount']),
        src_account=me if out else there,
        dst_account=there if out else me,
      )
    ]
    if fee is not None:
      moved.append(FeeLeg(**common, amount=fee.amount, event_type='internal_transfer'))
    return moved
  if kind == 'DEPOSIT' and status == 'COMPLETED':
    return [
      CryptoDeposit(
        **common,
        amount=row['amount'],
        network=row.get('chain'),
        tx_id=row.get('transactionHash'),
        fee=fee,
      )
    ]
  if kind == 'CLAIM' and status == 'COMPLETED':
    return [Bonus(**common, amount=row['amount'], category='claim')]
  if kind in WITHDRAWALS and status != 'REJECTED':
    return [
      CryptoWithdrawal(
        **common,
        amount=row['amount'],
        network=row.get('chain'),
        tx_id=row.get('transactionHash'),
        fee=fee,
      )
    ]
  return []


def fill(row: AccountTrade, markets: dict[str, MarketRow]) -> Observation:
  """One fill: a perpetual `FutureTrade` or a `SpotTrade`, the fee in the collateral.

  Fills carry no realised PnL; closed positions carry it.

  Raises:
    NotImplementedError: The fill paid a builder fee, which `fee` may or may not
      include (unobserved).
  """
  if row.get('builderFee'):
    raise NotImplementedError(
      'Extended builder fees are not supported: whether `fee` includes `builderFee` '
      'is unobserved'
    )
  market = markets[row['market']]
  quote = market['collateralAssetName']
  common: dict[str, Any] = {
    'id': f'trade:{row["id"]}',
    'time': row['createdTime'],
    'subaccount': str(row['accountId']),
    'base': market['assetName'],
    'quote': quote,
    'size': row['qty'] if row['side'] == 'BUY' else -row['qty'],
    'price': row['price'],
    'order_id': str(row['orderId']),
    'fee': Fee(amount=row['fee'], asset=quote),
  }
  if market['type'] == 'SPOT':
    return SpotTrade(**common, pair=row['market'])
  return FutureTrade(**common, instrument=row['market'], settle=quote)


def funding(row: FundingPayment, markets: dict[str, MarketRow]) -> Observation:
  """One hourly funding payment of a position, positive when received."""
  return Funding(
    id=f'funding:{row["id"]}',
    time=row['paidTime'],
    subaccount=str(row['accountId']),
    asset=markets[row['market']]['collateralAssetName'],
    amount=funding_received(row),
    instrument=row['market'],
    position_id=str(row['positionId']),
  )


def position(row: PositionHistory, markets: dict[str, MarketRow]) -> Observation:
  """One closed position's realised PnL breakdown.

  `realisedPnl = tradePnl + openFees + closeFees + fundingFees`, fees negative: the
  realised PnL is `tradePnl` and the fees are negated.
  """
  market = markets[row['market']]
  quote = market['collateralAssetName']
  parts = row.get('realisedPnlBreakdown')
  return FuturePositionSummary(
    id=f'position:{row["id"]}',
    time=row.get('closedTime'),
    subaccount=str(row['accountId']),
    position_id=str(row['id']),
    instrument=row['market'],
    base=market['assetName'],
    quote=quote,
    settle=quote,
    position_side='long' if row['side'] == 'LONG' else 'short',
    opened_at=row['createdTime'],
    closed_at=row.get('closedTime'),
    avg_entry_price=row['openPrice'],
    avg_close_price=row.get('exitPrice'),
    realized_pnl=parts['tradePnl'] if parts else None,
    funding=parts['fundingFees'] if parts else None,
    opening_fee=-parts['openFees'] if parts else None,
    closing_fee=-parts['closeFees'] if parts else None,
    total_fee=-(parts['openFees'] + parts['closeFees']) if parts else None,
    position_pnl=row['realisedPnl'],
  )


@dataclass(frozen=True, kw_only=True)
class Report(Public, SDKReport):
  """Snapshots and history of the sub-account an API key belongs to."""

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    *,
    network: Network = 'mainnet',
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a report from the sub-account's API key (read-only is enough); unset, the
    client reads `EXTENDED_API_KEY` (`EXTENDED_TESTNET_API_KEY` on testnet).

    Args:
      api_key: The sub-account's API key.
      network: `mainnet` or `testnet`.
      validate: Validate responses.
      account_id: Root SDK account key; defaults to the venue ID.
    """
    return cls(
      shared=Shared.new(
        api_key, network=network, validate=validate, account_id=account_id
      )
    )

  def record(self, observations: list[Observation], row: Any) -> HistoryRecord:
    """Observations with their provenance: the venue row."""
    return HistoryRecord(
      observations=observations,
      provenance={
        'source': 'api',
        'service': self.venue_id,
        'id': observations[0].id or '',
        'details': row,
      },
    )

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """The API key's sub-account, labelled by its `accountId`: every asset it holds,
    the collateral (`USD`) included, and its open perpetual positions by market.

    Args:
      assets: Ignored: the venue enumerates holdings.
    """
    account = self.shared.client.account
    info, balances, positions = await asyncio.gather(
      self.shared.call(account.info),
      self.shared.call(account.spot_balances),
      self.shared.call(account.positions),
    )
    snapshot = Snapshot(
      subaccounts=[subaccount_snapshot(info['accountId'], balances, positions)]
    )
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
    """Stream the sub-account's asset operations, then funding payments, fills and
    closed positions.

    Funding payments are positive when received. Fills (`trades`, newest first) are read
    back to `start`, at most the 10,000 most recent; closed positions carry the realised
    PnL, its fees and funding.

    Args:
      start: Inclusive lower bound; defaults to before Extended's launch.
      end: Inclusive upper bound; defaults to now.

    Raises:
      NotImplementedError: The window holds a borrow-interest payment, whose sign is
        unobserved; nothing is yielded then.
    """
    lower = start or EARLIEST
    upper = end or datetime.now(timezone.utc)
    if lower.tzinfo is None or upper.tzinfo is None:
      raise ValueError('History bounds must be timezone-aware')
    if upper < lower:
      raise ValueError('History end precedes start')
    client = self.shared.client
    me = (await self.shared.call(client.account.info))['accountId']
    interest = await self.shared.call(
      lambda: client.interest.payments([me], interval='ALL')
    )
    if any(lower <= p['timestamp'] <= upper for p in interest['items']):
      raise NotImplementedError(INTEREST_UNOBSERVED)
    assets = await self.shared.call(lambda: client.info.assets(type='SPOT'))
    names = {a['id']: a['name'] for a in assets}
    markets = dict(await self.shared.load_markets())
    operations = client.account.asset_operations_paged(
      start_time=lower, end_time=upper
    ).via(self.shared.call)
    async for page in operations:
      for row in page:
        if observations := operation(row, names):
          yield self.record(observations, row)
    payments = client.account.funding_history_paged(start_time=lower).via(
      self.shared.call
    )
    async for page in payments:
      for row in page:
        if lower <= row['paidTime'] <= upper:
          yield self.record([funding(row, markets)], row)
    trades = client.account.trades_paged().via(self.shared.call)
    async for page in trades:
      for row in page:
        if lower <= row['createdTime'] <= upper:
          yield self.record([fill(row, markets)], row)
      if page and page[-1]['createdTime'] < lower:
        break
    positions = client.account.positions_history_paged().via(self.shared.call)
    async for page in positions:
      for row in page:
        closed = row.get('closedTime')
        if closed is not None and lower <= closed <= upper:
          yield self.record([position(row, markets)], row)
