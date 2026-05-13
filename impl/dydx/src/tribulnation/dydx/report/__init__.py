"""dYdX SDK reporting surfaces."""

from dataclasses import dataclass

from tribulnation.sdk.reporting import Report as SdkReport

from .history import History
from .snapshots import Snapshots

@dataclass(frozen=True)
class Reporting(Snapshots, History, SdkReport):
  """dYdX reporting client with snapshots and history."""
