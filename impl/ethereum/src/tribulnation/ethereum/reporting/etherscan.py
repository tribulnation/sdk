from dataclasses import dataclass
from tribulnation.sdk.reporting import Report as _Report
from .snapshots import Snapshots
from .history import EtherscanHistory

@dataclass
class EtherscanReport(_Report, Snapshots, EtherscanHistory):
  ...
