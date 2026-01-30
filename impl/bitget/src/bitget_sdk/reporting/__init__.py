from dataclasses import dataclass
from .snapshots import Snapshots
from .transactions import Transactions

@dataclass
class Reporting(Snapshots, Transactions):
  ...