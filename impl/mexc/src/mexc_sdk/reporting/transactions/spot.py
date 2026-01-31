from typing_extensions import TypedDict, Required, Iterable
from datetime import timezone

from sdk.reporting.transactions import (
  SingleEvent, Event,
  Transaction, match_transactions
)
from .util import Module, UniqueIds
from .flows import spot_statement
from .events import fixed_earn, flexible_earn, deposits, withdrawals, spot_trades, fiat_otc_orders

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

def spot_transactions(
  paths: SpotPaths, tz: timezone, *,
  skip_zero_changes: bool = True
) -> Iterable[Transaction]:

  flows = list(spot_statement.parse(paths['spot_statement'], skip_zero_changes=skip_zero_changes))

  events: list[Event] = []
  for key, module in spot_modules.items():
    if (path := paths.get(key)) is not None:
      events.extend(module.parse(path, tz, skip_zero_changes=skip_zero_changes))
  
  matched_txs, other_flows = match_transactions(flows, events)
  yield from matched_txs

  ids = UniqueIds()
  for f in other_flows:
    id = ids.new(f'{f.label};{f.time:%Y-%m-%d %H:%M:%S}')
    yield Transaction.single(id, f)