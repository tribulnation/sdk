from typing_extensions import TypedDict, Required, Protocol, Iterable
from dataclasses import dataclass
from datetime import timezone
from glob import glob
import os

from trading_sdk.reporting.history import History, Event

from .flows import isolated_margin_transactions
from .events import isolated_margin_order_history

class Module(Protocol):
  @staticmethod
  def parse(path: str, tz: timezone) -> Iterable[Event]:
    ...

class IsolatedMarginPaths(TypedDict, total=False):
  isolated_margin_transactions: Required[str]
  isolated_margin_order_history: str

isolated_margin_modules: dict[str, Module] = {
  'isolated_margin_order_history': isolated_margin_order_history,
}

def isolated_margin_history(paths: IsolatedMarginPaths, tz: timezone) -> History.History:
  flows = list(isolated_margin_transactions.parse(paths['isolated_margin_transactions'], tz))

  events: list[Event] = []
  for key, module in isolated_margin_modules.items():
    if (path := paths.get(key)) is not None:
      events.extend(module.parse(path, tz))

  return History.History(
    flows=flows,
    events=events,
  )

@dataclass
class IsolatedMarginExport:
  paths: IsolatedMarginPaths

  @classmethod
  def autoload(cls, folder: str, *, log: bool = True):
    required_patterns = {
      'isolated_margin_transactions': 'Export isolated margin transactions-*.csv',
    }
    patterns = {
      'isolated_margin_order_history': 'Export isolated margin order history-*.csv',
    }
    paths: IsolatedMarginPaths = {} # type: ignore
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
