from typing_extensions import AsyncIterable
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import Report as SdkReport, Record
from .snapshots import Snapshots
from .history import EtherscanHistory
from .records import records as evm_records

@dataclass
class EtherscanReport(SdkReport, Snapshots, EtherscanHistory):
  """Etherscan-backed EVM reporting."""

  @SDK.method
  async def records(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Record]:
    """Fetch Etherscan records with EVM boundary snapshots."""
    async for record in evm_records(self, start=start, end=end):
      yield record
