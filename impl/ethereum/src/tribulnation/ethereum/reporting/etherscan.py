from typing_extensions import AsyncIterable
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import Report as _Report
from tribulnation.sdk.reporting import Record, EvmTx
from .snapshots import Snapshots
from .history import EtherscanHistory

@dataclass
class EtherscanReport(_Report, Snapshots, EtherscanHistory):
  @SDK.method
  async def records(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Record]:
    """Fetch Etherscan records with EVM boundary snapshots."""
    assets = set[str]()
    async for record in self.history(start, end):
      yield record
      for obs in record.observations:
        if isinstance(obs, EvmTx):
          for transfer in obs.transfers:
            assets.add(transfer.asset)
    if end is None:
      yield await self.snapshots(assets=assets)