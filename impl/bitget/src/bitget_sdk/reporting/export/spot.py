from typing_extensions import TypedDict, Required, Protocol, Iterable
from dataclasses import dataclass
from datetime import timezone
from glob import glob
import os

from trading_sdk.reporting.history import History, Event

from .flows import spot_transactions
from .events import spot_order_details, withdrawal_records

class Module(Protocol):
  @staticmethod
  def parse(path: str, tz: timezone) -> Iterable[Event]:
    ...

class SpotPaths(TypedDict, total=False):
  spot_transactions: Required[str]
  spot_order_details: str
  withdrawal_records: str

spot_modules: dict[str, Module] = {
  'spot_order_details': spot_order_details,
}

def spot_history(paths: SpotPaths, tz: timezone) -> History.History:
  flows = list(spot_transactions.parse(paths['spot_transactions'], tz))

  events: list[Event] = []
  for key, module in spot_modules.items():
    if (path := paths.get(key)) is not None:
      events.extend(module.parse(path, tz))

  if (path := paths.get('withdrawal_records')) is not None:
    events.extend(withdrawal_records.parse(path, tz))

  return History.History(
    flows=flows,
    events=events,
  )

@dataclass
class SpotExport:
  paths: SpotPaths

  @classmethod
  def autoload(cls, folder: str, *, log: bool = True):
    required_patterns = {
      'spot_transactions': 'Export spot transactions-*.csv',
    }
    patterns = {
      'spot_order_details': 'Export spot order details-*.csv',
      'withdrawal_records': 'withdrawal records-*.csv',
    }
    paths: SpotPaths = {} # type: ignore
    for key, pattern in required_patterns.items():
      matches = glob(os.path.join(folder, pattern))
      if len(matches) == 0:
        raise FileNotFoundError(f'No files found for {key} in {folder}')
      elif len(matches) > 1:
        raise ValueError(f'Multiple files found for {key} in {folder}')
      else:
        if log:
          print(f'[OK] Found file for {key} in {folder}: {matches[0]}')
      paths[key] = matches[0]

    for key, pattern in patterns.items():
      matches = glob(os.path.join(folder, pattern))
      if len(matches) == 0:
        if log:
          print(f'[WARN] No files found for {key} in {folder}, skipping')
      elif len(matches) > 1:
        if log:
          print(f'[WARN] Multiple files found for {key} in {folder}, skipping')
      else:
        if log:
          print(f'[OK] Found file for {key} in {folder}: {matches[0]}')
        paths[key] = matches[0]

    return cls(paths=paths)
