from typing_extensions import AsyncIterable, Protocol, Sequence
from datetime import datetime, timedelta

from tribulnation.sdk.reporting import EvmTx, Record, Snapshot
from .snapshots import source_id

class EvmRecordsSource(Protocol):
  """Object able to fetch EVM history records and snapshots."""

  def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Record]:
    """Fetch EVM history records."""
    ...

  async def snapshots(self, assets: Sequence[str] | None = None) -> Record:
    """Fetch an EVM balance snapshot."""
    ...

async def records(
  source: EvmRecordsSource, *,
  start: datetime | None = None,
  end: datetime | None = None,
) -> AsyncIterable[Record]:
  """Fetch EVM records with a derived zero baseline snapshot."""
  assets = set[str]()
  start_time: datetime | None = None
  async for record in source.history(start, end):
    yield record
    for obs in record.observations:
      if obs.time is not None:
        start_time = obs.time if start_time is None else min(start_time, obs.time)
      if isinstance(obs, EvmTx):
        for transfer in obs.transfers:
          assets.add(transfer.asset)

  if start is None and start_time is not None:
    snapshot_time = start_time - timedelta(days=1)
    yield Record(
      snapshots=[Snapshot(time=snapshot_time, balances={})],
      provenance={
        'source': 'derived',
        'id': source_id('derived'),
        'details': {
          'note': 'EVM full-history reports imply zero balances before the first observed transaction.',
        },
      },
    )

  if end is None:
    yield await source.snapshots(assets=sorted(assets))
