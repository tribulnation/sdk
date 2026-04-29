from .snapshots import Snapshots, Snapshot
from .history import History, Flow, Event

class Report(History, Snapshots):
  ...