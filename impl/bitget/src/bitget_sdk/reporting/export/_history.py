from typing_extensions import AsyncIterable
from dataclasses import dataclass
from datetime import datetime, timezone
import os

from trading_sdk.reporting.history import History as _History

from .spot import spot_history, SpotPaths, SpotExport
from .cross_margin import cross_margin_history, CrossMarginPaths, CrossMarginExport
from .isolated_margin import isolated_margin_history, IsolatedMarginPaths, IsolatedMarginExport
from .futures import futures_history, FuturesPaths, FuturesExport

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()

@dataclass
class ExportHistory(_History):
  """Parse history from Bitget CSV exports."""
  spot: SpotPaths | None = None
  cross_margin: CrossMarginPaths | None = None
  isolated_margin: IsolatedMarginPaths | None = None
  futures: FuturesPaths | None = None
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the files' times."""

  @classmethod
  def autoload(cls, folder: str, *, log: bool = True):
    spot = None
    cross_margin = None
    isolated_margin = None
    futures = None

    try:
      spot = SpotExport.autoload(folder, log=log).paths
    except FileNotFoundError:
      if log:
        print('[WARN] No spot exports found, skipping')

    try:
      cross_margin = CrossMarginExport.autoload(folder, log=log).paths
    except FileNotFoundError:
      if log:
        print('[WARN] No cross margin exports found, skipping')

    try:
      isolated_margin = IsolatedMarginExport.autoload(folder, log=log).paths
    except FileNotFoundError:
      if log:
        print('[WARN] No isolated margin exports found, skipping')

    try:
      futures = FuturesExport.autoload(folder, log=log).paths
    except FileNotFoundError:
      if log:
        print('[WARN] No futures exports found, skipping')

    if not any([spot, cross_margin, isolated_margin, futures]):
      raise FileNotFoundError(f'No Bitget export files found in {folder}')

    return cls(
      spot=spot,
      cross_margin=cross_margin,
      isolated_margin=isolated_margin,
      futures=futures,
    )

  @property
  def timezone(self) -> timezone:
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo # type: ignore
    else:
      return self.tz

  async def history(self, start: datetime, end: datetime) -> AsyncIterable[_History.History]:
    start = start.astimezone(self.timezone)
    end = end.astimezone(self.timezone)

    if self.spot is not None:
      spot = spot_history(self.spot, self.timezone)
      yield _History.History(
        flows=[f for f in spot.flows if start <= f.time <= end],
        events=[e for e in spot.events if start <= e.time <= end],
      )

    if self.cross_margin is not None:
      cross = cross_margin_history(self.cross_margin, self.timezone)
      yield _History.History(
        flows=[f for f in cross.flows if start <= f.time <= end],
        events=[e for e in cross.events if start <= e.time <= end],
      )

    if self.isolated_margin is not None:
      isolated = isolated_margin_history(self.isolated_margin, self.timezone)
      yield _History.History(
        flows=[f for f in isolated.flows if start <= f.time <= end],
        events=[e for e in isolated.events if start <= e.time <= end],
      )

    if self.futures is not None:
      futures = futures_history(self.futures, self.timezone)
      yield _History.History(
        flows=[f for f in futures.flows if start <= f.time <= end],
        events=[e for e in futures.events if start <= e.time <= end],
      )
