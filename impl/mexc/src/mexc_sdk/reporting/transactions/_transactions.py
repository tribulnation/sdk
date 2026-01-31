from typing_extensions import AsyncIterable
from glob import glob
from dataclasses import dataclass
from datetime import datetime, timezone
import os

from sdk.reporting import (
  Transaction, Transactions as TransactionsTDK
)

from .spot import spot_transactions, SpotPaths
from .futures import futures_transactions, FuturesPaths

class ExcelPaths(SpotPaths, FuturesPaths):
  ...

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()

@dataclass
class Transactions(TransactionsTDK):
  """Parse Transactions from the MEXC [data export](https://www.mexc.com/support/data-export).
  
  - `Futures` > `Futures Capital Flow` & `Futures Trade History`
  - `Spot` > `Spot Statement` & `Spot Trade History`
  - `Funding History` > `Deposit History` & `Withdrawal History`
  - `Fiat` > `OTC Orders`
  - `Earn` > `Fixed` & `Flexible`
  """
  paths: ExcelPaths
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the files' times."""
  skip_zero_changes: bool = True
  """Skip zero change operations."""

  @classmethod
  def autoload(cls, folder: str, *, log: bool = True):
    required_patterns = {
      'spot_statement': 'Spot-Spot Statement-*.xlsx',
      'futures_capital_flow': 'Futures-Futures Capital Flow-*.xlsx',
    }
    patterns = {
      'fixed_earn': 'Earn-Fixed-*.xlsx',
      'flexible_earn': 'Earn-Flexible-*.xlsx',
      'deposits': 'Funding History-Deposit History-*.xlsx',
      'withdrawals': 'Funding History-Withdrawal History-*.xlsx',
      'spot_trades': 'Spot-Spot Trade History-*.xlsx',
      'fiat_otc_orders': 'Fiat-OTC Orders-*.xlsx',
      'futures_trades': 'Futures-Futures Trade History-*.xlsx',
    }
    paths: ExcelPaths = {} # type: ignore
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

  @property
  def timezone(self) -> timezone:
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo # type: ignore
    else:
      return self.tz
  
  async def _transactions_impl(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[list[Transaction]]:
    if start is not None:
      start = start.astimezone(timezone.utc)
    if end is not None:
      end = end.astimezone(timezone.utc)
    
    def filter_time(tx: Transaction) -> bool:
      return (start is None or start <= tx.time) and (end is None or tx.time < end)

    for path in self.paths.values():
      if not os.path.exists(path): # type: ignore (yes path is a string, fucking pyright)
        raise FileNotFoundError(f'File not found: {path}')
    for tx in spot_transactions(self.paths, self.timezone, skip_zero_changes=self.skip_zero_changes):
      if filter_time(tx):
        yield [tx]
    for tx in futures_transactions(self.paths, self.timezone, skip_zero_changes=self.skip_zero_changes):
      if filter_time(tx):
        yield [tx]