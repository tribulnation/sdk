from typing_extensions import TypedDict, Required, Protocol, Iterable
from datetime import timezone

from trading_sdk.reporting.history import History, Event
from .flows import spot_statement
from .events import fixed_earn, flexible_earn, deposits, withdrawals, spot_trades, fiat_otc_orders

class Module(Protocol):
  @staticmethod
  def parse(path: str, tz: timezone) -> Iterable[Event]:
    ...

class SpotPaths(TypedDict, total=False):
  spot_statement: Required[str]
  fixed_earn: str
  flexible_earn: str
  deposits: str
  withdrawals: str
  spot_trades: str
  fiat_otc_orders: str

spot_modules: dict[str, Module] = {
  'fixed_earn': fixed_earn,
  'flexible_earn': flexible_earn,
  'deposits': deposits,
  'withdrawals': withdrawals,
  'spot_trades': spot_trades,
  'fiat_otc_orders': fiat_otc_orders,
}

def spot_history(paths: SpotPaths, tz: timezone) -> History.History:

  flows = list(spot_statement.parse(paths['spot_statement']))

  events: list[Event] = []
  for key, module in spot_modules.items():
    if (path := paths.get(key)) is not None:
      events.extend(module.parse(path, tz))
  
  return History.History(
    flows=flows,
    events=events,
  )