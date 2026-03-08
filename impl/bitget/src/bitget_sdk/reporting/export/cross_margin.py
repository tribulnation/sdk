from typing_extensions import TypedDict, Required, Protocol, Iterable
from dataclasses import dataclass
from datetime import timezone
from glob import glob
import os

from trading_sdk.reporting.history import History, Event

from .flows import cross_margin_transactions
from .events import cross_margin_order_history

class Module(Protocol):
  @staticmethod
  def parse(path: str, tz: timezone) -> Iterable[Event]:
    ...

class CrossMarginPaths(TypedDict, total=False):
  cross_margin_transactions: Required[str]
  cross_margin_order_history: str

cross_margin_modules: dict[str, Module] = {
  'cross_margin_order_history': cross_margin_order_history,
}

def cross_margin_history(paths: CrossMarginPaths, tz: timezone) -> History.History:
  flows = list(cross_margin_transactions.parse(paths['cross_margin_transactions'], tz))

  events: list[Event] = []
  for key, module in cross_margin_modules.items():
    if (path := paths.get(key)) is not None:
      events.extend(module.parse(path, tz))

  return History.History(
    flows=flows,
    events=events,
  )

@dataclass
class CrossMarginExport:
  paths: CrossMarginPaths

  @classmethod
  def autoload(cls, folder: str, *, log: bool = True):
    required_patterns = {
      'cross_margin_transactions': 'Export cross margin transactions-*.csv',
    }
    patterns = {
      'cross_margin_order_history': 'Export cross margin order history-*.csv',
    }
    paths: CrossMarginPaths = {} # type: ignore
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
