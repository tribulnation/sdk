from dataclasses import dataclass
from .snapshots import Snapshots
from .history import History

@dataclass
class Reporting(Snapshots, History):
  ...