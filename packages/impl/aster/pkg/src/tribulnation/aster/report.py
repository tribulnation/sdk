"""Aster cash ledgers as unclassified observations; snapshots are unsupported.

Not routed through `ReportSDK`: it is qualified on testnet only.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import AsyncIterable, Collection
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Report as SDKReport,
  SnapshotRecord,
  UnknownObservation,
)
from .core import Public

DEFAULT_LOOKBACK = timedelta(days=7)
PAGE = 1000


@dataclass(frozen=True, kw_only=True)
class Report(Public, SDKReport):
  """Perpetual income and spot transaction ledgers, without classification."""

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Unsupported: testnet account information omits funded spot balances."""
    raise NotImplementedError('Aster snapshots are not supported')

  def record(
    self,
    *,
    subaccount: str,
    id: str,
    time: datetime,
    asset: str,
    amount: Decimal,
    details: object,
  ) -> HistoryRecord:
    """Wrap one native cash delta, identified by `subaccount:id`."""
    return HistoryRecord(
      observations=[
        UnknownObservation(
          id=id, time=time, subaccount=subaccount, asset=asset, amount=amount
        )
      ],
      provenance={
        'source': 'api',
        'service': self.venue_id,
        'id': f'{subaccount}:{id}',
        'details': details,
      },
    )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Stream perpetual income, then spot transactions, as cash deltas.

    Args:
      start: Inclusive lower bound; defaults to seven days before `end`.
      end: Inclusive upper bound; defaults to now.
    """
    upper = end or datetime.now(timezone.utc)
    lower = start or upper - DEFAULT_LOOKBACK
    if lower.tzinfo is None or upper.tzinfo is None:
      raise ValueError('History bounds must be timezone-aware')
    if upper < lower:
      raise ValueError('History end precedes start')
    income = self.client.futures.account.income_paged(
      start_time=lower, end_time=upper, limit=PAGE
    )
    async for page in income.via(self.shared.call):
      for row in page:
        yield self.record(
          subaccount='perp',
          id=f'{row["incomeType"]}:{row["tranId"]}',
          time=row['time'],
          asset=row['asset'],
          amount=row['income'],
          details=row,
        )
    transactions = self.client.spot.account.transaction_history_paged(
      start_time=lower, end_time=upper, limit=PAGE
    )
    async for page in transactions.via(self.shared.call):
      for row in page:
        # One spot transaction ID spans several asset/type legs.
        yield self.record(
          subaccount='spot',
          id=f'{row["type"]}:{row["asset"]}:{row["tranId"]}',
          time=row['time'],
          asset=row['asset'],
          amount=row['balanceDelta'],
          details=row,
        )
