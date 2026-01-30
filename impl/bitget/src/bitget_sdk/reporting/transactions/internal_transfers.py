from typing_extensions import Mapping, MutableSequence
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from sdk.reporting.transactions import InternalTransfer, Strategy, Transaction

def _match_transfers_impl(
  transfers: dict[int, InternalTransfer], *,
  match_multiple: bool, max_time: timedelta, max_amount: Decimal
) -> list[tuple[int, int]]:
  matches: list[tuple[int, int]] = []

  for k, e in list(transfers.items()):
    if k not in transfers:
      continue
    candidates = [
      k2 for k2, e2 in transfers.items()
      if e2.asset == e.asset and abs(e2.qty + e.qty) < max_amount and abs(e.time - e2.time) < max_time
    ]
    if len(candidates) == 1 or (len(candidates) > 1 and match_multiple):
      k2 = candidates[0]
      matches.append((k, k2))
      del transfers[k2]
  
  return matches

def match_transfers(
  transfers: Mapping[int, InternalTransfer],
  *,
  max_time: timedelta = timedelta(seconds=15),
  max_amount: Decimal = Decimal(0.01)
) -> list[tuple[int, int]]:
  transfers_idx = dict(transfers)
  matches = _match_transfers_impl(transfers_idx, match_multiple=False, max_time=max_time, max_amount=max_amount)
  if transfers_idx:
    matches2 = _match_transfers_impl(transfers_idx, match_multiple=True, max_time=max_time, max_amount=max_amount)
    matches.extend(matches2)
  return matches


def parse_internal_transfers(transactions: MutableSequence[Transaction]):
  """Matches internal transfers. Unmatched transfers are changed to strategy deposits/withdrawals.
  
  This is necessary because Bitget doesn't give access to copy trading (and perhaps others) transactions. Thus we treat them as black boxes.
  """
  internal_transfers = {
    i: tx.event for i, tx in enumerate(transactions) if tx.event.type == 'internal_transfer'
  }
  matches = match_transfers(internal_transfers)
  unmatched = set(internal_transfers.keys()) - set(i for m in matches for i in m)
  for i in unmatched:
    tx = transactions[i]
    e = tx.event
    assert isinstance(e, InternalTransfer)
    assert len(tx.flows) == 1
    assert tx.flows[0].label == 'internal_transfer'
    label = 'strategy_deposit' if tx.flows[0].change < 0 else 'strategy_withdrawal'
    flow = replace(tx.flows[0], label=label)
    event = Strategy(
      type=label,
      id=e.id, time=e.time, details=e.details,
      qty=e.qty, asset=e.asset,
    )
    transactions[i] = replace(tx, event=event, flows=[flow])