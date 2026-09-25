"""Aster's verified native cash observations; full snapshots remain blocked."""

from datetime import datetime, timedelta, timezone
from typing_extensions import AsyncIterable, Collection
from dataclasses import dataclass
from tribulnation.sdk.reporting import (
  Report as SDKReport,
  SnapshotRecord,
  HistoryRecord,
  UnknownObservation,
)
from .core import SharedMixin


@dataclass(frozen=True, kw_only=True)
class Report(SharedMixin, SDKReport):
  """Read unclassified cash observations without claiming a complete economic ledger."""

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Avoid an incomplete account snapshot while native spot balances are missing."""
    raise NotImplementedError(
      'Testnet spot account.info omits funded balances; see testnet-issues.md'
    )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Preserve native cash-ledger deltas as unclassified observations, scoped by bucket."""
    upper = end or datetime.now(timezone.utc)
    lower = start or upper - timedelta(days=7)
    if lower.utcoffset() is None or upper.utcoffset() is None or upper < lower:
      raise ValueError('Expected aware, ordered bounds')
    async for page in self.client.futures.account.income_paged(
      start_time=lower, end_time=upper, limit=1000
    ).via(self.call_aster):
      for row in page:
        identity = f'perp:income:{row["incomeType"]}:{row["tranId"]}'
        yield HistoryRecord(
          observations=[
            UnknownObservation(
              id=str(row['tranId']),
              time=row['time'],
              subaccount='perp',
              asset=row['asset'],
              amount=row['income'],
            )
          ],
          provenance={
            'source': 'api',
            'service': self.shared.venue_id,
            'id': identity,
            'details': row,
          },
        )
    async for page in self.client.spot.account.transaction_history_paged(
      start_time=lower, end_time=upper, limit=1000
    ).via(self.call_aster):
      for entry in page:
        yield HistoryRecord(
          observations=[
            UnknownObservation(
              id=f'{entry["tranId"]}:{entry["type"]}:{entry["asset"]}',
              time=entry['time'],
              subaccount='spot',
              asset=entry['asset'],
              amount=entry['balanceDelta'],
            )
          ],
          provenance={
            'source': 'api',
            'service': self.shared.venue_id,
            'id': f'spot:transaction:{entry["tranId"]}:{entry["type"]}:{entry["asset"]}',
            'details': entry,
          },
        )
