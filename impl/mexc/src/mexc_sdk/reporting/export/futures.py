from typing_extensions import TypedDict, Required
from datetime import timezone

from trading_sdk.reporting.history import History, Event

from .flows import futures_capital_flow
from .events import futures_trades

class FuturesPaths(TypedDict, total=False):
  futures_capital_flow: Required[str]
  futures_trades: str

def futures_history(paths: FuturesPaths, tz: timezone) -> History.History:
  flows = list(futures_capital_flow.parse(paths['futures_capital_flow']))

  events: list[Event] = []
  if (path := paths.get('futures_trades')) is not None:
    events.extend(futures_trades.parse(path, tz))

  return History.History(
    flows=flows,
    events=events,
  )