from typing_extensions import TypedDict, Required
from dataclasses import dataclass
from datetime import timezone
from glob import glob
import os

from trading_sdk.reporting.history import History, Event

from .flows import futures_transactions
from .events import futures_transaction_details

class FuturesPaths(TypedDict, total=False):
  futures_transactions: Required[list[str]]
  futures_transaction_details: list[str]


def futures_history(paths: FuturesPaths, tz: timezone) -> History.History:
  flows = []
  for path in paths['futures_transactions']:
    flows.extend(futures_transactions.parse(path, tz))

  events: list[Event] = []
  for path in paths.get('futures_transaction_details', []):
    events.extend(futures_transaction_details.parse(path, tz))

  return History.History(flows=flows, events=events)


@dataclass
class FuturesExport:
  paths: FuturesPaths

  @classmethod
  def autoload(cls, folder: str, *, log: bool = True):
    tx_pattern = 'Export futures transactions-*.csv'
    detail_pattern = 'Export futures transaction details-*.csv'

    tx_matches = sorted(glob(os.path.join(folder, tx_pattern)))
    if len(tx_matches) == 0:
      raise FileNotFoundError(f'No files found for futures_transactions in {folder}')
    if log:
      print(f'[OK] Found {len(tx_matches)} futures transactions file(s) in {folder}')
      for m in tx_matches:
        print(f'  - {m}')

    detail_matches = sorted(glob(os.path.join(folder, detail_pattern)))
    if len(detail_matches) == 0:
      if log:
        print(f'[WARN] No files found for futures_transaction_details in {folder}, skipping')
    else:
      if log:
        print(f'[OK] Found {len(detail_matches)} futures transaction details file(s) in {folder}')
        for m in detail_matches:
          print(f'  - {m}')

    paths: FuturesPaths = {
      'futures_transactions': tx_matches,
    }
    if detail_matches:
      paths['futures_transaction_details'] = detail_matches

    return cls(paths=paths)
