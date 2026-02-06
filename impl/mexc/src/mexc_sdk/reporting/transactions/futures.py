from typing_extensions import TypedDict, Required
from datetime import timezone

from tribulnation.sdk.reporting.transactions import (
  Event, Transaction, match_transactions
)

from .util import UniqueIds
from .flows import futures_capital_flow
from .events import futures_trades

class FuturesPaths(TypedDict, total=False):
  futures_capital_flow: Required[str]
  futures_trades: str

def futures_transactions(
  paths: FuturesPaths, tz: timezone, *,
  skip_zero_changes: bool = True
):
  flows = list(futures_capital_flow.parse(paths['futures_capital_flow'], skip_zero_changes=skip_zero_changes))

  events: list[Event] = []
  if (path := paths.get('futures_trades')) is not None:
    events = list(futures_trades.parse(path, tz, skip_zero_changes=skip_zero_changes))

  matched_txs, other_flows = match_transactions(flows, events)
  yield from matched_txs

  ids = UniqueIds()
  for f in other_flows:
    id = ids.new(f'{f.label};{f.time:%Y-%m-%d %H:%M:%S}')
    yield Transaction.single(id, f)